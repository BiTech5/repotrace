"""Capture layer for RepoTrace.

Turns a failing command execution into structured trace artifacts: the
command that ran, its output, the surrounding environment, and enough
metadata to rebuild a :class:`~reprotrace.storage.BugReport`.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reprotrace.storage import BugReport


class TraceEvent(BaseModel):
    """A single ordered step recorded while a command runs."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(..., description="Zero-based position of the event in the trace")
    kind: str = Field(
        ...,
        description="Event category, e.g. command, stdout, stderr, exit, error",
    )
    message: str = Field(..., description="Human readable payload of the event")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Time the event was recorded",
    )
    data: dict[str, object] = Field(
        default_factory=dict,
        description="Structured details attached to the event",
    )


def collect_environment(cwd: Path | str | None = None) -> dict[str, Any]:
    """Gather host metadata that helps explain why a run failed.

    Args:
        cwd: Working directory to report. Defaults to the interpreter's
            current working directory.

    Returns:
        A JSON-serialisable mapping of interpreter, platform, and path info.
    """
    workdir = Path(cwd) if cwd is not None else Path.cwd()
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cwd": str(workdir),
    }


class Trace(BaseModel):
    """An ordered record of everything observed for one captured run."""

    model_config = ConfigDict(frozen=True)

    command: list[str] = Field(
        default_factory=list,
        description="Argv of the process that was executed",
    )
    cwd: str = Field(default="", description="Working directory of the run")
    exit_code: int | None = Field(
        None, description="Process exit code, or None if it never finished"
    )
    events: list[TraceEvent] = Field(
        default_factory=list, description="Chronological events of the run"
    )
    environment: dict[str, Any] = Field(
        default_factory=dict, description="Host metadata captured with the trace"
    )

    @classmethod
    def start(
        cls,
        command: list[str],
        cwd: Path | str | None = None,
    ) -> Trace:
        """Create a trace for ``command`` and record its opening event."""
        workdir = Path(cwd) if cwd is not None else Path.cwd()
        trace = cls(
            command=list(command),
            cwd=str(workdir),
            environment=collect_environment(workdir),
        )
        return trace.add(
            kind="command",
            message=" ".join(command),
            data={"argv": list(command)},
        )

    def add(
        self,
        kind: str,
        message: str,
        data: dict[str, object] | None = None,
    ) -> Trace:
        """Return a copy of the trace with one more event appended."""
        event = TraceEvent(
            index=len(self.events),
            kind=kind,
            message=message,
            data=data or {},
        )
        return self.model_copy(update={"events": [*self.events, event]})

    def of_kind(self, kind: str) -> list[TraceEvent]:
        """Return every event recorded with ``kind``."""
        return [event for event in self.events if event.kind == kind]


def run_capture(
    command: list[str],
    cwd: Path | str | None = None,
    timeout: float | None = None,
) -> Trace:
    """Execute ``command`` and record its outcome as a :class:`Trace`.

    The subprocess shares this interpreter's streams only through the
    captured output; stdout and stderr are read back as text and appended
    as events so failures remain inspectable after the process exits.

    Args:
        command: Argv to execute.
        cwd: Working directory for the child process.
        timeout: Seconds to wait before the process is killed.

    Returns:
        A trace containing the command, environment, output, and exit code.

    Raises:
        FileNotFoundError: If the executable does not exist.
        subprocess.TimeoutExpired: If ``timeout`` elapses first.
    """
    trace = Trace.start(command, cwd=cwd)
    workdir = Path(trace.cwd) if trace.cwd else None
    completed = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.stdout:
        trace = trace.add(kind="stdout", message=completed.stdout)
    if completed.stderr:
        trace = trace.add(kind="stderr", message=completed.stderr)
    trace = trace.add(
        kind="exit",
        message=f"exit code {completed.returncode}",
        data={"exit_code": completed.returncode},
    )
    return trace.model_copy(update={"exit_code": completed.returncode})


def build_report(
    trace: Trace,
    title: str | None = None,
    report_id: str | None = None,
    **overrides: Any,
) -> BugReport:
    """Derive a :class:`BugReport` from a captured :class:`Trace`.

    Args:
        trace: The captured run to describe.
        title: Optional title; defaults to a summary of the command.
        report_id: Optional identifier; defaults to a stable hash of the argv.
        **overrides: Extra :class:`BugReport` field values, e.g. ``severity``.

    Returns:
        An unsaved bug report carrying the full trace as metadata.
    """
    if report_id is None:
        report_id = hashlib.sha1(" ".join(trace.command).encode()).hexdigest()[:12]
    if title is None:
        summary = " ".join(trace.command)
        failed = trace.exit_code not in (0, None)
        title = (
            f"Command failed: {summary}" if failed else f"Command captured: {summary}"
        )

    payload: dict[str, Any] = {
        "id": report_id,
        "title": title,
        "tags": ["capture"],
        "metadata": {
            "exit_code": trace.exit_code,
            "cwd": trace.cwd,
            "environment": trace.environment,
            "events": [event.model_dump(mode="json") for event in trace.events],
        },
    }
    payload.update(overrides)
    return BugReport(**payload)
