"""Read a permission block from an OpenCode config and write a test config."""

import json
import re
from typing import Any


class ConfigError(ValueError):
    """The config parses as JSON but has no usable permission object."""


def strip_jsonc(txt: str) -> str:
    """Remove // and /* */ comments outside strings, then trailing commas."""
    out: list[str] = []
    i, n = 0, len(txt)
    while i < n:
        c = txt[i]
        if c == '"':
            j = i + 1
            while j < n and txt[j] != '"':
                j += 2 if txt[j] == "\\" else 1
            out.append(txt[i : j + 1])
            i = j + 1
        elif txt.startswith("//", i):
            k = txt.find("\n", i)
            i = n if k < 0 else k
        elif txt.startswith("/*", i):
            i = txt.find("*/", i) + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_perm(txt: str) -> dict[str, Any]:
    """Return the "permission" object of a config, or the whole thing if it is a bare one.

    A bare permission object may carry a "$schema" key for editors; it is not a
    rule, and OpenCode rejects it inside "permission", so it is dropped.
    """
    data = json.loads(strip_jsonc(txt))
    if not isinstance(data, dict):
        raise ConfigError("config is not a JSON object")
    perm: object = data.get("permission", data)
    if not isinstance(perm, dict):
        raise ConfigError('"permission" is not a JSON object')
    return {k: v for k, v in perm.items() if k != "$schema"}


def write_config(path: str, src_config: str, port: int) -> None:
    """Write an opencode.json that uses the stub model on `port` and src_config's permissions."""
    with open(src_config) as f:
        perm = load_perm(f.read())
    cfg = {
        "autoupdate": False,
        "share": "disabled",
        "model": "stub/stub",
        "small_model": "stub/stub",
        "provider": {
            "stub": {
                "npm": "@ai-sdk/openai-compatible",  # built into OpenCode, not downloaded
                "name": "stub",
                "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "fake"},
                "models": {"stub": {"name": "stub", "tool_call": True}},
            }
        },
        "permission": perm,
    }
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
