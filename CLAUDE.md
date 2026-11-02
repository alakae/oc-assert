# oc-assert

An OpenCode permission config: commands that cannot change anything run
without asking, everything else asks. The aim is to cut approval prompts
without allowing anything that writes files, runs programs, or reaches outside
the workspace.
The repository also holds `oc-assert`, which tests the config against the real
OpenCode binary.

Tested with OpenCode 1.19.4, 1.19.5 and 2.2.4. OpenCode changes often: re-run
the tests after every upgrade.

## Files

- `opencode.jsonc`: the config, with comments. Its object becomes the value of
  `permission` in `opencode.json`, without the `"$schema"` line (OpenCode
  1.19.5 and later reject it there).
- `opencode.cases`: the test cases for the config (187).
- `src/oc_assert/`: the `oc-assert` tool. For each case it starts the
  real OpenCode binary against a fake model server that asks it to run one
  command, and compares the result (RUN, ASK or DENY) with the expected one.
  - `cli.py`: arguments, setup checks, parallel run, report
  - `cases.py`: cases file parser
  - `config.py`: reads the commented config, writes each case's opencode.json
  - `fake_server.py`: stub OpenAI-compatible model that requests the command
  - `runner.py`: workspace, isolated environment, running OpenCode, verdict
  - `__main__.py`: lets `python3 -m oc_assert` run it without uv
- `ci/opencode/<version>/`: npm lockfiles pinning each tested OpenCode version.

## Quick start

```sh
# test the config (needs opencode on PATH, or pass --opencode PATH)
uv run oc-assert opencode.jsonc opencode.cases
# the same with only Python's standard library, no uv
PYTHONPATH=src python3 -m oc_assert opencode.jsonc opencode.cases

# install: make the object in opencode.jsonc (minus "$schema") the value of
# "permission" in ~/.config/opencode/opencode.json or a project opencode.json
```

`oc-assert` exits with 0 if all cases pass, 1 if any fails, and 2 on a setup
error.

## Cases file format

One case per line: `VERDICT  command`, where VERDICT is RUN, ASK or DENY.
Blank lines and `#` comments are ignored. `VERDICT@MAJOR` (e.g. `ASK@2`) limits
a case to one OpenCode major version; `oc-assert` detects the version and skips
the others. Commands run for real in a temporary workspace, so keep them benign
and self-contained.

```
RUN   git status
ASK   git push
ASK   cat .env
RUN@1 cd && ls
```

## OpenCode 1.x and 2.x

- 2.x is published on npm as `@opencode/cli`; `opencode-ai` stops at 1.19.5.
- 2.x calls its shell tool `shell` and reads the permission key as `bash` or
  `shell`; 1.x reads only `bash`. Keep `bash` while 1.x matters.
- 2.x runs sessions through a shared background service. `oc-assert` passes
  `--standalone` on 2.x so parallel cases don't interfere (1.x rejects the
  flag).

## How the config is built

1. The bash block starts with `"*": "ask"`, and allows come after it. The last
   matching rule wins, so an allow pattern must never start with `*`: it would
   override every ask before it.
2. Commands that cannot write or run anything whatever their flags (cat, head,
   grep, wc, diff, ls, ...) are allowed with any arguments. Commands that can
   with some flag (sort, uniq, ps) are allowed in exact forms only, never with
   a trailing `*`. `"X *"` also matches a bare `X`, so bare forms need no rule
   of their own.
3. Tools with an embedded language are left out entirely: sed, awk, jq, xargs,
   perl, `python -c`. Glob rules can't make them safe.
4. Search tools depend on how their options work:
   - `rg` and `git grep` have many options, the risky ones are long-only, and
     git accepts abbreviated options, so listing risky options by name can't
     keep up. Every long option asks (`rg *--*`, `git grep *--*`); searches
     with short options run. A long option may be re-allowed only as an exact
     form (`rg --files`), never with a trailing `*`.
   - `find` has a fixed set of actions, so asking for the ones that run,
     delete or write (`-exec`, `-ok`, `-delete`, `-fprint`, `-fls`) covers it.
   - Other read-only git commands ask for the options that write or run
     (`--output`, `--ext-diff`, `--textconv`).
5. Catch-all asks come last: redirects (`*>*`), backticks, `$` (variables and
   `$(...)`), paths outside the workspace (`* /*`, `* ~*`, `* ..` and their
   quoted and `=` forms), and `.env` files.
6. Top level: `"*": "ask"`, so unknown or renamed tools ask; `read` allowed
   except `.env` files; glob, grep, todowrite and skill allowed; edit,
   webfetch, websearch, task and external_directory ask.

## Known gaps

No rule can stop these; `opencode.cases` records them as expected:

- `export X=1` and bare `VAR=value`: OpenCode never checks them.
- A bare `cd` on 1.x: only a path argument is checked (via
  external_directory), and a bare `cd` goes to `$HOME`, so `cd && ls` lists it.
  2.x asks.
- A repository whose `.git/config` already sets `diff.external` or a textconv
  driver: a plain `git diff` runs that program. Writing that config asks.
- Symlinks that already point outside the workspace.
- A project-level OpenCode config that overrides this one (not tested).

The config reduces prompts; it is not a security boundary. To contain all of
the above, run OpenCode in a sandbox (for example Docker Sandboxes) with only
the workspace mounted and no secrets in its environment.

## Tests run offline

`oc-assert` gives OpenCode a minimal environment: only `PATH` is inherited, and
every proxy setting, including npm's, points at a closed port. Only the fake
model server on localhost is reachable. The model provider is built into
OpenCode, so nothing is downloaded. (Without the block, 1.x fetches npm
metadata for `@opencode-ai/plugin` on every run; the result doesn't depend on
it.) A case that tries the network, such as `curl`, fails if it ever runs.

## Working on the project

- After changing `opencode.jsonc`, run
  `uv run oc-assert opencode.jsonc opencode.cases`. Add a case for every new
  rule, one that fails without it, and keep the suite green.
- Before committing Python changes, run
  `uv run ruff format && uv run ruff check && uv run mypy`. mypy runs in strict
  mode; all three must be clean.

## CI and releases

- `.github/workflows/ci.yml` runs on pushes to main, pull requests and `v*`
  tags: ruff and mypy, then `opencode.cases` on OpenCode 1.19.4, 1.19.5 and 2.2.4.
  On a `v*` tag, if every job passes, it creates a GitHub release with
  `opencode.jsonc` attached. Only that job can write to the repository.
- Each OpenCode version is installed with `npm ci --ignore-scripts` from its
  lockfile in `ci/opencode/<version>/`, and CI runs the platform binary
  directly (`opencode-linux-x64` for 1.x, `@opencode/cli-linux-x64` for 2.x).
  The lockfile pins it by checksum. OpenCode's install script only copies that
  binary into place, or downloads an unpinned one if that fails, so skipping it
  loses nothing. To add a version: copy `ci/opencode/<version>/package.json`
  from an existing one, run `npm install --package-lock-only --ignore-scripts`
  in that folder, and add the version and binary path to the matrix in
  `ci.yml`.
- Each job prints the runner image version and the tools it uses. GitHub
  updates the runner image without notice, so that output shows what changed
  when a run breaks without a commit.
- `.github/workflows/workflow-lint.yml` runs zizmor (1.31.1) and actionlint
  (1.7.12) on the workflows. Both must stay clean.
- Actions are pinned to commit SHAs with pinact. To upgrade them, run
  `pinact run -u -m 14` (newest releases at least 14 days old), then zizmor
  and actionlint. pinact needs GitHub API access.
