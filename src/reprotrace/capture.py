"""Capture layer for RepoTrace.

Turns a failing command execution into structured trace artifacts: the
command that ran, its output, the surrounding environment, and enough
metadata to rebuild a :class:`~reprotrace.storage.BugReport`.
"""

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
