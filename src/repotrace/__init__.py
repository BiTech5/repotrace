"""RepoTrace — turn failing commands into reproducible bug reports.

The package is organised as a pipeline:

- :mod:`repotrace.storage` — the ``BugReport`` schema and JSON-file store.
- :mod:`repotrace.capture` — run a command and record its trace.
- :mod:`repotrace.generator` — flatten a failure and emit a pytest regression
  test.
- :mod:`repotrace.replay` — re-run a recorded command and compare it with the
  record.
- :mod:`repotrace.report` — render reports and replay sweeps as Markdown.
- :mod:`repotrace.cli` — the ``repotrace`` command line interface.

``main`` is re-exported so ``repotrace = "repotrace:main"`` in ``pyproject.toml``
resolves to the Typer application.
"""

from __future__ import annotations

from repotrace.cli import app, main

__all__ = ["app", "main"]

__version__ = "0.1.0"
