"""Capture layer for RepoTrace.

Turns a failing command execution into structured trace artifacts: the
command that ran, its output, the surrounding environment, and enough
metadata to rebuild a :class:`~reprotrace.storage.BugReport`.
"""

from datetime import UTC, datetime

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
