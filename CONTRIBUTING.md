# Contributing to RepoTrace

Thanks for taking the time to contribute. This document covers the conventions
that matter here, so please read it before opening a pull request.

## Before you start

1. **Read the existing code first.** RepoTrace is deliberately layered, and the
   layers depend on each other in one direction only. Match the patterns that
   already exist rather than inventing a parallel structure.
2. **Read `AGENTS.md`.** It carries the mandatory session workflow, the tech
   stack constraints, and the agent contribution policies. This file does not
   repeat it; where the two disagree, `AGENTS.md` wins.
3. **Check `docs/sessions/`.** At the start of every task, read the most recent
   session file to see what is already done. Do not redo completed modules —
   build on them.

## Setup

```bash
uv sync
```

This installs the package in editable mode plus the `dev` dependency group
(`pytest`, `ruff`). Requires **Python 3.12 or newer**.

Activate the environment if you want the `repotrace` console script on your
`PATH`:

```bash
source .venv/bin/activate
```

## Running the checks

```bash
# Tests
.venv/bin/python -m pytest

# A single module's tests — preferred while iterating
.venv/bin/python -m pytest tests/test_replay.py -q

# Lint and format
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests
```

Validate with the **narrowest relevant test command** for your change. Run the
full suite before opening a pull request.

Note that `ruff format` reformats any file you point it at, including ones you
did not touch. Run it against the specific paths you changed, and check
`git diff` before committing so an unrelated file does not slip in.

## Making changes

### Keep changes small and targeted

Each change should do one thing. If you find yourself refactoring a module you
are not otherwise touching, stop — that belongs in its own change with its own
justification.

### Respect the layer boundaries

The architecture is a pipeline, and the dependencies point one way:

```
storage ──► capture ──► generator ──► replay ──► report ──► cli
```

- `storage.py` — the `BugReport` schema and the `ReportStore`. Depends on
  nothing else in the package.
- `capture.py` — runs commands and records traces. Depends on `storage`.
- `generator.py` — flattens a failure and emits tests. Depends on `capture` and
  `storage`.
- `replay.py` — re-runs recorded commands. Depends on `capture`, `generator`,
  and `storage`.
- `report.py` — renders output. Depends on `replay` and `storage`, and
  deliberately does **not** import the CLI.
- `cli.py` — the Typer application. Depends on everything.

Two rules follow from this:

1. **Do not add a back-edge.** `report.py` must not import `cli.py`. The
   rendering functions are pure string building so they stay usable from scripts
   and tests.
2. **Do not duplicate flattening logic.** `Reproduction` in `generator.py` is
   the single place that turns a `Trace` or a `BugReport` into a runnable
   command. `replay.py` reuses it rather than re-parsing metadata. If you need
   the recorded argv or output, go through `Reproduction` or factor the helper
   you need into `generator.py` alongside it.

### Data is immutable

`BugReport`, `Trace`, `TraceEvent`, `Reproduction`, `ReplayResult`,
`ReplaySummary`, and `ReportSection` are all frozen Pydantic models. Use
`model_copy(update={...})` to derive a new value instead of mutating one, and
add `ConfigDict(frozen=True)` to any new model.

### Validation and formatting

- Use Pydantic v2 models with `Field(..., description=...)` so the schema stays
  self-documenting.
- Follow the existing docstring style: purpose, then `Args:`, `Returns:`, and
  `Raises:` where relevant. Be concise.
- Use modern builtin generics (`str | None`, `list[str]`, `dict[str, Any]`) and
  `from __future__ import annotations`. `ruff` is configured to require this.
- Add a test for every behavioural change, bug fix, and new feature.

### Where tests go

One test module per source module, named `tests/test_<module>.py`:

```
tests/test_storage.py
tests/test_capture.py
tests/test_generator.py
tests/test_replay.py
tests/test_report.py
tests/test_cli.py
```

Tests use `tmp_path` for filesystem work and keep recorded commands host
independent — a bare `python -c ...` rather than an absolute `sys.executable`,
because an absolute path makes output comparisons machine specific.

The CLI tests use `typer.testing.CliRunner`. Note that Typer options must be
placed **before** the positional argument they belong to, and that `capture`
requires `context_settings={"ignore_unknown_options": True,
"allow_extra_args": True}` so it can pass a command's own flags through.

## Commit conventions

- Commit in small, logical units. Backend core, CLI, and docs go in separate
  commits.
- Do not force push.
- **Do not co-author your own commits.** Commit authorship is assigned to the
  human engineer responsible for the change — no `Co-authored-by` trailer from an
  agent. When committing on someone's behalf, set the author explicitly:
  `git commit --author="Name <email>"`.
- Write a subject line that says what changed, not what file was edited.

## Session summaries

At the end of a task, offer to write a session summary to `docs/sessions/`. Name
it sequentially — the next file after `006-cli-module.md` would be
`007-<topic>.md` — and cover what changed, what was validated, and what comes
next.

`docs/sessions/` is gitignored by design ("Ignore local AI session logs"), so
session files stay local. Do not force them into history with `git add -f`.

## Common pitfalls

- **Assuming an event's shape.** Events reach the rendering layer as serialised
  dicts, not as `TraceEvent` models. Read fields through a helper that tolerates
  both (`report._event_field`), or you will get `None` everywhere.
- **Looking for `metadata["command"]`.** `capture.build_report` does not set
  it — the argv lives in the first `command` event. Use the helper that already
  exists rather than adding a second copy of that lookup.
- **`ruff format` on the whole tree.** It will reformat untouched files and
  pollute your diff.
- **Testing Rich markup as plain text.** `render_result_line` returns Rich markup
  (`` `matched` ``), not a rendered string. Assert on the markup, or strip it.
- **Piping generated output through Rich.** The CLI prints rendered Markdown
  with `markup=False, highlight=False`. Do the same if you add a command that
  emits Markdown.

## Reporting bugs

Open an issue with the command you ran, the output you saw, and — if RepoTrace
itself is misbehaving — the relevant report JSON from `.repotrace/reports/`.
That file is usually the fastest way to reproduce the problem.
