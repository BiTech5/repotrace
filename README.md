# RepoTrace

RepoTrace turns a failing command into something you can keep: a structured bug
report carrying the command, its output, and the environment it ran in — which
you can then re-run to check whether the failure still reproduces, render as a
Markdown document, or convert into a committed `pytest` regression test.

The point is reproducibility. A bug report that only says "it failed" is hard to
act on; one that stores the exact argv, exit code, stdout, stderr, working
directory, and interpreter version can be replayed at any later date and will
tell you honestly whether the failure is still there.

## Installation

RepoTrace requires **Python 3.12 or newer**.

Install the published package from PyPI:

```bash
pip install repotrace
```

Or with `uv`:

```bash
uv add repotrace
```

If you are working from a local checkout, use an editable install instead:

```bash
# From a checkout, editable install (recommended for development)
uv sync

# Or with pip
pip install -e .
```

This provides the `repotrace` console script.

## Quick start

Capture a failing command. Note that the command is passed through verbatim, so
its own flags (`-c`, `--flag`, …) are not interpreted by RepoTrace:

```bash
repotrace capture python -m pytest tests/test_thing.py -q
```

This prints the captured report id and exit code, and writes a JSON report to
`.repotrace/reports/<id>.json`. `capture` exits with the command's own exit
code, so it can sit directly in a shell pipeline.

```bash
repotrace list
repotrace show <id>

# Does it still fail the same way?
repotrace replay <id>

# Or does the whole corpus still reproduce?
repotrace replay-all
```

## The workflow

```
capture ──► report store ──► replay ──► report / generate
                │                              │
                └──────────── list / show ◄────┘
```

1. **Capture** a failing command. Its argv, output, exit code, working
   directory, and host metadata are recorded as a `BugReport` and persisted as
   one JSON file under the store.
2. **List and inspect** what you have stored.
3. **Replay** a report to re-run the recorded command and compare the result
   against the record.
4. **Report** a report as Markdown, optionally with its replay verdict baked in.
5. **Generate** a standalone regression test that re-runs the recorded command
   and asserts nothing changed.

## Command reference

### `capture`

Run a command, record its trace, and persist a bug report.

```bash
repotrace capture [OPTIONS] COMMAND...
```

| Option | Description |
| --- | --- |
| `--store, -s PATH` | Report store directory. Default `.repotrace/reports`. |
| `--cwd PATH` | Working directory for the run. |
| `--timeout SECONDS` | Seconds to wait before the command is killed. |
| `--title TEXT` | Title for the report (default: a summary of the command). |
| `--id TEXT` | Report id (default: a fresh UUID4). |
| `--overwrite` | Replace an existing report with the same id. |
| `--severity TEXT` | Severity, e.g. `high`. |
| `--tags TEXT` | Comma-separated tags, e.g. `flaky,ci`. |
| `--keep-going` | Exit 0 even when the captured command failed. |

```bash
repotrace capture --severity high --tags flaky,ci \
  python -c "import sys; print('boom'); sys.exit(7)"
```

Captured stdout and stderr are echoed to the console as well as stored.

Each capture gets a new UUID4 by default, so running the same command again
keeps both reports. You can still supply a custom `--id`. Reusing an existing
id exits with code 2 and leaves the stored report unchanged, unless you pass
`--overwrite` before the command to replace it deliberately.
Place all RepoTrace options before `COMMAND`; arguments after it belong to
the captured command, including any `--overwrite` option of its own.

### `list`

Print the id of every stored report, one per line, followed by a count. Prints
`no reports stored` for an empty store.

```bash
repotrace list [--store PATH]
```

### `show`

Print one report's fields and metadata as a table.

```bash
repotrace show [--store PATH] REPORT_ID [--markdown]
```

`--markdown` renders the full Markdown document instead of the summary table.

### `replay`

Re-run a stored command and compare it with the recorded failure.

```bash
repotrace replay [OPTIONS] REPORT_ID
```

| Option | Description |
| --- | --- |
| `--store, -s PATH` | Report store directory. |
| `--cwd PATH` | Working directory (default: the recorded one). |
| `--timeout SECONDS` | Seconds to wait before the command is killed. |
| `--exit-code-only` | Compare exit codes only, ignoring captured output. |
| `--keep-going` | Exit 0 even when the replay no longer reproduces. |

Use `--exit-code-only` when the captured output contains machine-specific paths
that will legitimately differ between machines.

### `replay-all`

Replay every stored report and summarise the outcomes.

```bash
repotrace replay-all [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--store, -s PATH` | Report store directory. |
| `--cwd PATH` | Working directory (default: each recorded one). |
| `--timeout SECONDS` | Seconds to wait before each command is killed. |
| `--exit-code-only` | Compare exit codes only, ignoring captured output. |
| `--output, -o PATH` | Write the sweep as Markdown to this file. |
| `--overwrite` | Replace the output file if it already exists. |
| `--keep-going` | Exit 0 even when some replays no longer reproduce. |

Reports that raise during replay — for example a report with no usable command —
are counted as failures rather than aborting the sweep.

### `report`

Render a stored report as Markdown.

```bash
repotrace report [OPTIONS] REPORT_ID
```

| Option | Description |
| --- | --- |
| `--store, -s PATH` | Report store directory. |
| `--output, -o PATH` | Write the Markdown report to this file. |
| `--overwrite` | Replace the output file if it already exists. |
| `--replay` | Replay the report first and include the verdict. |
| `--no-metadata` | Omit the metadata section. |
| `--no-events` | Omit the event listing. |

### `generate`

Emit a standalone `pytest` regression test from a stored report.

```bash
repotrace generate [OPTIONS] REPORT_ID
```

| Option | Description |
| --- | --- |
| `--store, -s PATH` | Report store directory. |
| `--output, -o PATH` | Destination test file (default: stdout). |
| `--name TEXT` | Test function name (default: derived from the report id). |
| `--exit-code-only` | Assert the exit code only, not captured output. |
| `--overwrite` | Replace the output file if it already exists. |

The generated module embeds the command and expected output as literals, so it
runs with no RepoTrace installation and can be committed next to the project.

### `version`

Print the installed RepoTrace version.

## Exit codes

RepoTrace is designed to be usable from scripts and CI, so its exit codes are
part of the interface:

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | A captured command failed, or a replay no longer reproduces. |
| `2` | Usage or lookup error: a missing report, a missing binary, an unwritable output path. |

`capture` propagates the captured command's own exit code. Use `--keep-going` on
`capture`, `replay`, or `replay-all` to force `0` regardless.

## Examples

### Capture and inspect

```console
$ repotrace capture --id 5303b4f97c12 python -c "import sys; print('boom'); sys.exit(7)"
captured 5303b4f97c12
exit code 7
boom

$ repotrace list
5303b4f97c12

1 report(s)

$ repotrace show 5303b4f97c12
                              Report 5303b4f97c12
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field       ┃ Value                                                          ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ id          │ 5303b4f97c12                                                   │
│ title       │ Command failed: python -c import sys; print('boom'); sys.exit(7) │
│ status      │ open                                                           │
│ severity    │ —                                                              │
│ tags        │ capture                                                        │
│ created_at  │ 2026-10-18 04:05:48.298051+00:00                               │
└─────────────┴────────────────────────────────────────────────────────────────┘

metadata
  cwd: '/tmp/demo'
  exit_code: 7
  events: [...]
```

### Replay a single report

```console
$ repotrace replay 5303b4f97c12
5303b4f97c12 `matched` — no differences

$ echo $?
0
```

### Sweep the whole store

```console
$ repotrace replay-all
                    Replay summary
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Report       ┃ Outcome    ┃ Exit code ┃ Differences ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ 5303b4f97c12 │ reproduced │         7 │ none        │
└──────────────┴────────────┴───────────┴─────────────┘
replayed 1 · reproduced 1 · differs 0 · failed 0 · reproducibility 100%
```

### Render a Markdown report with its verdict

```console
$ repotrace report 5303b4f97c12 --replay
5303b4f97c12 `matched` — no differences
# Replay report — reproduced

## Summary
**ID:** `5303b4f97c12`
**Status:** open
**Severity:** —
**Tags:** capture
**Created:** 2026-10-18 04:05:48 UTC

## Replay outcome
**Outcome:** `matched` (reproduced)
**Exit code:** 7 (recorded 7)
**Working directory:** `/tmp/demo`
**Command:** `python -c import sys; print('boom'); sys.exit(7)`

Differences: none

## Metadata
- **cwd:** /tmp/demo
- **exit_code:** `int`
- **events:** `list`
- **environment:** `dict`

## Events
- 0. `command`: python -c import sys; print('boom'); sys.exit(7)
- 1. `stdout`: boom
- 2. `exit`: exit code 7
```

### Write a Markdown sweep to a file

```console
$ repotrace replay-all -o sweep.md
wrote sweep.md

$ cat sweep.md
# Replay summary

**Reports replayed:** 1
**Reproduced:** 1
**No longer reproduce:** 0
**Failed to run:** 0
**Reproducibility:** 100%

| Report | Outcome | Exit code | Differences |
| --- | --- | --- | --- |
| `5303b4f97c12` | `matched` | 7 | none |
```

### Generate a regression test

```console
$ repotrace generate 5303b4f97c12 -o tests/test_regression_5303.py
wrote tests/test_regression_5303.py

$ pytest tests/test_regression_5303.py
.                                                                        [100%]
1 passed in 0.01s
```

The generated test looks like this:

```python
"""Regression test generated by RepoTrace.

Report: 5303b4f97c12
Title: Command failed: python -c import sys; print('boom'); sys.exit(7)
Recorded command: python -c import sys; print('boom'); sys.exit(7)
Recorded exit code: 7
"""

import subprocess

COMMAND = ['python', '-c', "import sys; print('boom'); sys.exit(7)"]
EXPECTED_EXIT_CODE = 7
EXPECTED_STDOUT = 'boom\n'
EXPECTED_STDERR = ''


def test_regression_5303b4f97c12() -> None:
    result = subprocess.run(COMMAND, capture_output=True, text=True)

    assert result.returncode == EXPECTED_EXIT_CODE
    assert result.stdout == EXPECTED_STDOUT
    assert result.stderr == EXPECTED_STDERR
```

## Library usage

Every command has a programmatic equivalent, so RepoTrace can be embedded in
tooling rather than driven through the shell.

`ReportStore.save(report)` raises `FileExistsError` if the id already exists.
Pass `overwrite=True` to `save` or `capture_command` only when you intend to
replace that report.

```python
from repotrace.capture import capture_command
from repotrace.replay import replay_from_store
from repotrace.report import format_report
from repotrace.storage import ReportStore

store = ReportStore(".repotrace/reports")

# Capture and persist.
trace, report = capture_command(
    ["python", "-m", "pytest", "tests/"],
    store=store,
    severity="high",
)

# Replay it.
result = replay_from_store(report.id, store)
print(result.outcome, result.differences)   # Outcome.MATCHED []

# Render a Markdown report with the verdict.
print(format_report(report, result=result))
```

### Module map

| Module | Responsibility |
| --- | --- |
| `repotrace.storage` | The `BugReport` schema and the JSON-file `ReportStore`. |
| `repotrace.capture` | `Trace`, `TraceEvent`, `run_capture`, `build_report`, `capture_command`. |
| `repotrace.generator` | `Reproduction` plus `generate_test` / `write_test`. |
| `repotrace.replay` | `Outcome`, `ReplayResult`, `ReplaySummary`, and the `replay*` functions. |
| `repotrace.report` | `format_report`, `format_replays`, and their write counterparts. |
| `repotrace.cli` | The `repotrace` Typer application. |

### Key API

```python
from repotrace.capture import Trace, run_capture, build_report, capture_command
from repotrace.storage import BugReport, ReportStore
from repotrace.generator import Reproduction, generate_test, write_test
from repotrace.replay import (
    Outcome, ReplayResult, ReplaySummary,
    replay, replay_report, replay_from_store, replay_all, diff,
)
from repotrace.report import (
    format_report, write_report, format_replays, write_replays,
    render_result_line, build_summary, outcome_label,
)
```

Notable signatures:

```python
replay(source, *, cwd=None, timeout=None, match_output=True) -> ReplayResult
replay_from_store(report_id, store, *, cwd=None, timeout=None,
                  match_output=True) -> ReplayResult
replay_all(store, *, cwd=None, timeout=None, match_output=True) -> ReplaySummary
format_report(report, *, result=None, include_metadata=True,
               include_events=True) -> str
format_replays(summary, *, max_rows=None) -> str
generate_test(source, *, function_name=None, match_output=True) -> str
```

`replay` accepts a `Reproduction`, a `Trace`, or a `BugReport`, so the same
call works on a fresh capture or a persisted report. `diff(result)` returns a
JSON-serialisable mapping of expected-versus-observed values.

## Report store

Reports live as one JSON file per report under the store root, which defaults to
`.repotrace/reports` and is created on demand:

```
.repotrace/
└── reports/
    ├── 5303b4f97c12.json
    └── a1b2c3d4e5f6.json
```

Because the store is plain JSON, reports can be inspected, diffed, and committed
alongside a project. Point the CLI at a different location with `--store`, or
construct `ReportStore(path)` directly.

## Development

```bash
# Install the package and dev dependencies
uv sync

# Run the test suite
uv run pytest

# Lint and format
uv run ruff check src tests
uv run ruff format src tests
```

The test suite covers each module in isolation (`tests/test_storage.py`,
`test_capture.py`, `test_generator.py`, `test_replay.py`, `test_report.py`) plus
the CLI surface (`tests/test_cli.py`).

### Tech stack

- Python 3.12+
- Typer — CLI
- Pydantic v2 — data validation
- Rich — console output
- pytest — testing

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT LICENSE](LICENSE)
