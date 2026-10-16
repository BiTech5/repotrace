"""Capture layer for RepoTrace.

Turns a failing command execution into structured trace artifacts: the
command that ran, its output, the surrounding environment, and enough
metadata to rebuild a :class:`~reprotrace.storage.BugReport`.
"""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
