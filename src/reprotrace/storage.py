"""Persistence layer for bug reports captured by RepoTrace.

The store keeps one JSON file per report inside a root directory
(``.reprotrace/reports`` by default), which makes results easy to inspect,
diff, and version alongside a project.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BugReport(BaseModel):
    """Schema for a captured Python failure and its diagnostic context."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique identifier for the bug report")
    title: str = Field(..., description="Title of the bug report")
    description: str | None = Field(None, description="Detailed description of the bug")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when the bug report was created",
    )
    updated_at: datetime | None = Field(
        None, description="Timestamp when the bug report was last updated"
    )
    status: str = Field(
        default="open",
        description="Current status of the bug report (e.g., open, closed, in progress)",
    )
    severity: str | None = Field(
        None, description="Severity level of the bug (e.g., low, medium, high)"
    )
    reporter: str | None = Field(
        None, description="Name or identifier of the person who reported the bug"
    )
    assignee: str | None = Field(
        None, description="Name or identifier of the person assigned to fix the bug"
    )
    tags: list[str] = Field(
        default_factory=list, description="List of tags associated with the bug report"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata related to the bug report"
    )


class ReportStore:
    """JSON-file backed store for :class:`BugReport` objects.

    Each report is persisted as ``<root>/<id>.json``. The root directory is
    created on demand, so constructing a store is always safe.
    """

    def __init__(self, root: Path | str = ".reprotrace/reports") -> None:
        """Create a store rooted at ``root``, creating the directory if needed."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, report_id: str) -> Path:
        """Return the on-disk path for ``report_id``."""
        return self.root / f"{report_id}.json"

    def save(self, report: BugReport) -> Path:
        """Persist ``report``, refreshing ``updated_at``, and return its path."""
        stored = report.model_copy(update={"updated_at": datetime.now(UTC)})
        path = self._path(stored.id)
        path.write_text(stored.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, report_id: str) -> BugReport:
        """Load and validate a single report by identifier.

        Raises:
            FileNotFoundError: If no report with ``report_id`` exists.
        """
        path = self._path(report_id)
        return BugReport.model_validate_json(path.read_text(encoding="utf-8"))

    def delete(self, report_id: str) -> bool:
        """Delete a report, returning ``True`` if one was removed."""
        path = self._path(report_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, report_id: str) -> bool:
        """Return whether a report with ``report_id`` is stored."""
        return self._path(report_id).exists()

    def list_ids(self) -> list[str]:
        """Return all stored report identifiers in sorted order."""
        return sorted(path.stem for path in self.root.glob("*.json"))

    def list(self) -> list[BugReport]:
        """Load and return every stored report."""
        return [self.load(report_id) for report_id in self.list_ids()]
