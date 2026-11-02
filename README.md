# oc-assert

A permission config for [OpenCode](https://opencode.ai) that cuts approval
prompts, and `oc-assert`, the tool that tests it against the real OpenCode.
Commands that cannot change anything run without asking: reading files,
searching, `git status`, `git log` and similar.
Everything that could write files, run programs, use the network or reach
outside the project asks first.

Tested on OpenCode 1.19.4, 1.19.5 and 2.2.4.

**This is not a security boundary.** It reduces approval prompts; it does not
contain a misbehaving agent. A few things can't be caught by permission rules
at all (see [Known gaps](#known-gaps)). If that matters to you, run OpenCode in
a sandbox with only the project mounted and no secrets in its environment.

## Install

[`opencode.jsonc`](opencode.jsonc) holds one JSON object: the permission
rules. Make it the value of `permission` in your OpenCode config, either
`~/.config/opencode/opencode.json` or an `opencode.json` in your project, and
leave out its `"$schema"` line (it is only there for editors; OpenCode rejects
it inside `permission`):

```jsonc
{
  "permission": {
    "*": "ask",
    "read": "allow",
    // ... the rest of opencode.jsonc
  }
}
```

Releases also attach `opencode.jsonc` as a file.

## How it decides

- Unknown tools, file edits, web fetches and subagents ask.
- Reading files is allowed.
- Shell commands ask unless an allow rule matches. Allowed are commands that
  can't write or run anything (`cat`, `grep`, `ls`, `wc`, ...), read-only git
  commands, and searches with `rg`, `git grep` and `find`.
- Options that would make an allowed command write or run something ask: for
  example `find -exec`, `find -delete`, `git diff --output`, any long option
  of `rg` or `git grep`, `rg -z`, `git grep -O`, and `sort -o`.
- Redirects (`>`), command substitution, variables (`$HOME`), and paths outside
  the project (`/etc`, `~`, `..`) always ask, including paths attached to an
  option (`grep -f/etc/x`).
- Glob rules can't stay inside one word, so a few ordinary commands ask too:
  `git grep -n TODO` (an `O` after a `-`), `rg -n x conf/` (an `f/`
  after a `-`), and any command with a brace, such as `rg 'a{2}'`. Braces
  and some quotes can build a path outside the project (`cat {/etc/x,}`,
  `cat '.'./x`), so they always ask.

The config file explains each rule in a comment.

## Known gaps

These run without asking, and no permission rule can stop them:

- `export X=1` and `VAR=value`, which OpenCode never checks.
- On OpenCode 1.x, a bare `cd` (it goes to your home folder), so `cd && ls`
  lists it. OpenCode 2.x asks.
- A plain `git diff` in a repository whose `.git/config` already runs an
  external diff program.
- Symlinks that already point outside the project.

## Testing the config

The tests are in [`opencode.cases`](opencode.cases): one shell command per
line with the expected result, RUN or ASK. The `oc-assert` tool runs each
command through the real OpenCode binary, against a fake model that asks for
that one command, in a temporary workspace with no network access. It needs
only Python 3.10 or newer and git.

```sh
# with uv
uv run oc-assert opencode.jsonc opencode.cases

# with plain Python, no installation
PYTHONPATH=src python3 -m oc_assert opencode.jsonc opencode.cases
```

`oc-assert` uses the `opencode` on your `PATH`, or the one given with
`--opencode PATH`. It exits with 0 when every case passes and 1 when one
fails. Re-run it after upgrading OpenCode: permission handling changes between
releases.

The commands run for real, inside throwaway folders. Keep new cases harmless.

## More

[`CLAUDE.md`](CLAUDE.md) has the details: the design rules behind the config,
the differences between OpenCode 1.x and 2.x, how the tests are isolated, and
how CI and releases work.
