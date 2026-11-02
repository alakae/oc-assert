"""Parse a cases file: one `VERDICT[@MAJOR]  command` per line.

A case with @MAJOR (e.g. `ASK@2`) applies only to that OpenCode major version.
"""

from typing import Literal, NamedTuple

Verdict = Literal["RUN", "ASK", "DENY"]

VERDICTS: dict[str, Verdict] = {"RUN": "RUN", "ASK": "ASK", "DENY": "DENY"}


class Case(NamedTuple):
    expected: Verdict
    command: str
    line: int
    major: int | None = None  # only for this OpenCode major version


class CasesError(ValueError):
    pass


def parse_cases(path: str) -> list[Case]:
    """Read the cases in `path`. Raises CasesError on bad input."""
    cases = []
    with open(path) as f:
        for ln, raw in enumerate(f, 1):
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split(None, 1)
            word, _, ver = parts[0].upper().partition("@")
            verdict = VERDICTS.get(word)
            if len(parts) != 2 or verdict is None or (ver and not ver.isdigit()):
                raise CasesError(
                    f"{path}:{ln}: expected 'RUN|ASK|DENY[@MAJOR] <command>', got: {raw.rstrip()}"
                )
            cases.append(Case(verdict, parts[1], ln, int(ver) if ver else None))
    if not cases:
        raise CasesError(f"{path}: no cases")
    return cases
