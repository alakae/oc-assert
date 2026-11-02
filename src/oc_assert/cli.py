"""oc-assert -- unit-test an OpenCode permission config against a real OpenCode.

Each test case is a bash command with an expected verdict. For every case the
tool launches the actual `opencode` binary, headless, pointed at a fake local
model server that asks it to run that one command. OpenCode's permission layer
then allows the command (RUN), auto-rejects it as needing approval (ASK), or
blocks it by a deny rule (DENY). The observed verdict is compared to the
expected one. Any mismatch fails the run (exit code 1).

Because it drives the real binary, the result is specific to the OpenCode
version on PATH (or named with --opencode). No real model is involved, and
OpenCode runs without network access.

cases file:
    One case per line.  <VERDICT>[@MAJOR]<whitespace><command>
    VERDICT is RUN, ASK or DENY (case-insensitive). With @MAJOR the case only
    applies to that OpenCode major version and is skipped on others.
    Blank lines and lines starting with # are ignored.
    The command runs verbatim; keep it on one line.
    Example:
        RUN   git status
        ASK   git push
        DENY  curl http://evil
        RUN@1 cd && ls

exit codes: 0 all pass, 1 one or more fail, 2 setup/usage error

safety: each case runs in its own temporary workspace (a git repo with a
committed a.txt containing "hello"), with its own HOME and no network.
Commands execute for real, so keep cases benign and self-contained.
"""

import argparse
import concurrent.futures as cf
import os
import shutil
import sys
import time
from collections.abc import Sequence
from typing import NoReturn

from .cases import Case, parse_cases
from .config import load_perm
from .runner import Outcome, Settings, opencode_major, run_case


def setup_error(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="oc-assert",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("config", help='opencode config holding "permission"')
    ap.add_argument("cases", help="cases file")
    ap.add_argument("-j", type=int, default=8, dest="jobs", help="parallel cases")
    ap.add_argument("--opencode", default=shutil.which("opencode") or "opencode")
    ap.add_argument("--timeout", type=int, default=60, help="seconds per case")
    ap.add_argument("-v", action="store_true", dest="verbose", help="print all cases")
    return ap.parse_args(argv)


def setup(a: argparse.Namespace) -> tuple[Settings, list[Case]]:
    """Load the config, cases and OpenCode version; exit with code 2 on any problem."""
    try:
        with open(a.config) as f:
            load_perm(f.read())
        cases = parse_cases(a.cases)
    except (OSError, ValueError) as e:  # CasesError and ConfigError are ValueErrors
        setup_error(str(e))
    opencode = os.path.abspath(a.opencode)
    major = opencode_major(opencode)
    if major is None:
        setup_error(f"cannot run {opencode} --version; pass --opencode PATH")
    return Settings(a.config, opencode, a.timeout, major), cases


def run_all(
    cases: list[Case], settings: Settings, jobs: int
) -> list[tuple[Outcome, str]]:
    """Run every case in parallel; returns (outcome, detail) in case order."""
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(lambda c: run_case(c.command, settings), cases))


def main(argv: Sequence[str] | None = None) -> NoReturn:
    a = parse_args(argv)
    settings, all_cases = setup(a)
    cases = [c for c in all_cases if c.major in (None, settings.major)]
    t0 = time.time()
    fails = 0
    for case, (got, detail) in zip(cases, run_all(cases, settings, a.jobs)):
        ok = got == case.expected
        fails += not ok
        if not ok or a.verbose:
            mark = "ok  " if ok else "FAIL"
            print(
                f"{mark} L{case.line:<4} want {case.expected:4} got {got:4}  {case.command}"
            )
            if not ok:
                print(f"         detail: {detail}")
    print(
        f"\nOpenCode {settings.major}.x: {len(cases)} cases, {fails} failed, "
        f"{len(cases) - fails} passed, {len(all_cases) - len(cases)} skipped "
        f"(other version)  ({time.time() - t0:.0f}s)"
    )
    sys.exit(1 if fails else 0)
