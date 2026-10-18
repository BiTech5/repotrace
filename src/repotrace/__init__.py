"""RepoTrace — turn failing commands into reproducible bug reports.

The package is organised as a pipeline:

- :mod:`reprotrace.storage` — the ``BugReport`` schema and JSON-file store.
- :mod:`reprotrace.capture` — run a command and record its trace.
- :mod:`reprotrace.generator` — flatten a failure and emit a pytest regression
  test.
- :mod:`reprotrace.replay` — re-run a recorded command and compare it with the
  record.
- :mod:`reprotrace.report` — render reports and replay sweeps as Markdown.
- :mod:`reprotrace.cli` — the ``reprotrace`` command line interface.

``main`` is re-exported so ``reprotrace = "reprotrace:main"`` in ``pyproject.toml``
resolves to the Typer application.
"""

from __future__ import annotations

from reprotrace.cli import app, main

__all__ = ["app", "main"]

__version__ = "0.1.0"
