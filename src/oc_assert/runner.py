"""Run one case through a real OpenCode and classify the verdict."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Literal

from . import fake_server
from .config import write_config

Outcome = Literal["RUN", "ASK", "DENY", "ERR"]


@dataclass(frozen=True)
class Settings:
    """What every case is run with."""

    config: str  # opencode config holding the permissions under test
    opencode: str  # path to the opencode binary
    timeout: int  # seconds per case
    major: int  # OpenCode major version, from opencode_major()


def opencode_major(opencode: str) -> int | None:
    """Major version of the opencode binary, or None if it can't be told.

    1.x prints "1.19.5"; 2.x prints "opencode v2.2.4".
    """
    try:
        out = subprocess.run(
            [opencode, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.\d+", out)
    return int(m.group(1)) if m else None


def make_workspace(ws: str) -> None:
    """Create the case workspace: a git repo with a committed a.txt ("hello")."""
    os.makedirs(ws)
    with open(os.path.join(ws, "a.txt"), "w") as f:
        f.write("hello\n")
    git = ["git", "-C", ws, "-c", "user.email=t@t", "-c", "user.name=t"]
    git += ["-c", "commit.gpgsign=false"]
    for args in (["init", "-q"], ["add", "a.txt"], ["commit", "-qm", "init"]):
        subprocess.run(git + args, capture_output=True, check=True)


# Every proxy setting points here, so nothing in a case can reach the network.
NO_NETWORK = "http://127.0.0.1:9"


def isolated_env(root: str, cfg: str) -> dict[str, str]:
    """A minimal environment: only PATH is inherited, everything else is local.

    OpenCode gets a throwaway HOME and XDG dirs, and no network: every proxy
    (including npm's own settings) points at a closed port, except for the fake
    model server on localhost. OpenCode 1.x otherwise fetches npm metadata for
    @opencode-ai/plugin in the background on every run; the verdicts don't
    depend on it, and the model provider is built into both 1.x and 2.x.
    """
    dirs = {
        name: os.path.join(root, name) for name in ("home", "xc", "xd", "xs", "cache")
    }
    for d in dirs.values():
        os.makedirs(d)
    proxies = {k: NO_NETWORK for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
    proxies |= {k.lower(): v for k, v in proxies.items()}
    return dict(
        PATH=os.environ.get("PATH", "/usr/bin:/bin"),
        # OpenCode takes its working directory from $PWD, not the process cwd;
        # a wrong PWD would run cases outside the throwaway workspace.
        PWD=os.path.join(root, "ws"),
        HOME=dirs["home"],
        XDG_CONFIG_HOME=dirs["xc"],
        XDG_DATA_HOME=dirs["xd"],
        XDG_STATE_HOME=dirs["xs"],
        XDG_CACHE_HOME=dirs["cache"],
        **proxies,
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
        npm_config_registry=NO_NETWORK + "/",
        npm_config_proxy=NO_NETWORK,
        npm_config_https_proxy=NO_NETWORK,
        npm_config_offline="true",
        OPENCODE_CONFIG=cfg,
        OPENCODE_DISABLE_AUTOUPDATE="1",
        OPENCODE_DISABLE_MODELS_FETCH="1",
        OPENCODE_DISABLE_LSP_DOWNLOAD="1",
    )


def run_case(cmd: str, settings: Settings) -> tuple[Outcome, str]:
    """Run `cmd` through OpenCode under the permissions in settings.config.

    Returns (outcome, detail). Each case has its own folders, so parallel cases
    never share state.
    """
    root = tempfile.mkdtemp(prefix="ocA.")
    srv, port = fake_server.start(cmd)
    try:
        ws = os.path.join(root, "ws")
        make_workspace(ws)
        cfg = os.path.join(root, "opencode.json")
        write_config(cfg, settings.config, port)
        # 2.x shares a background service between runs unless --standalone,
        # which mixes up parallel cases; 1.x has no such flag and rejects it.
        standalone = ["--standalone"] if settings.major >= 2 else []
        p = subprocess.run(
            [
                settings.opencode,
                *standalone,
                "run",
                "--format",
                "json",
                "run the probe",
            ],
            cwd=ws,
            env=isolated_env(root, cfg),
            capture_output=True,
            text=True,
            timeout=settings.timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        return classify(p.stdout, p.stderr)
    except subprocess.TimeoutExpired:
        return "ERR", "timeout"
    except subprocess.CalledProcessError as e:
        return "ERR", f"workspace setup failed: {e}"
    finally:
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def classify(stdout: str, stderr: str) -> tuple[Outcome, str]:
    """Turn OpenCode's JSON event stream into (outcome, detail).

    The last shell tool event decides: completed means it ran; an error with
    OpenCode's auto-reject message on stderr means it would have asked; any
    other error means a deny rule blocked it.
    """
    state: dict[str, Any] | None = None
    for line in stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("type") != "tool_use":
            continue
        if e["part"].get("tool") in fake_server.SHELL_TOOLS:
            state = e["part"].get("state")
    if state is None:
        return "ERR", stderr.strip()[-160:] or "no shell tool event"
    if state.get("status") == "completed":
        return "RUN", str(state.get("output", "")).strip().replace("\n", " ")[:80]
    err = str(state.get("error", ""))
    if "auto-rejecting" in stderr:
        return "ASK", err[:120]
    return "DENY", err[:160]
