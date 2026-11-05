from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from repotrace.storage import BugReport


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def report_exit_code(report: BugReport) -> int | None:
    
    value = report.metadata.get("exit_code")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


class ReportFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None = Field(
        None, description="Case-insensitive substring of the report title"
    )
    tags: tuple[str, ...] = Field(
        default_factory=tuple, description="Tags the report must contain"
    )
    severity: str | None = Field(
        None, description="Severity to match, compared case-insensitively"
    )
    exit_code: int | None = Field(
        None, description="Exit code recorded in the report metadata"
    )
    since: datetime | None = Field(
        None, description="Inclusive lower bound on the creation timestamp"
    )
    until: datetime | None = Field(
        None, description="Inclusive upper bound on the creation timestamp"
    )

    @model_validator(mode="after")
    def _validate_range(self) -> ReportFilter:
        """Reject a range whose lower bound is after its upper bound."""
        if (
            self.since is not None
            and self.until is not None
            and _as_utc(self.since) > _as_utc(self.until)
        ):
            raise ValueError("`since` must be on or before `until`")
        return self


def _matches(report: BugReport, criteria: ReportFilter) -> bool:
    if (
        criteria.title is not None
        and criteria.title.casefold() not in report.title.casefold()
    ):
        return False

    if criteria.tags:
        report_tags = {tag.casefold() for tag in report.tags}
        if any(tag.casefold() not in report_tags for tag in criteria.tags):
            return False

    if (
        criteria.severity is not None
        and (report.severity or "").casefold() != criteria.severity.casefold()
    ):
        return False

    if (
        criteria.exit_code is not None
        and report_exit_code(report) != criteria.exit_code
    ):
        return False

    created_at = _as_utc(report.created_at)
    if criteria.since is not None and created_at < _as_utc(criteria.since):
        return False
    return criteria.until is None or created_at <= _as_utc(criteria.until)


def filter_reports(
    reports: Iterable[BugReport], criteria: ReportFilter | None = None
) -> list[BugReport]:
    active = criteria or ReportFilter()
    matches = [report for report in reports if _matches(report, active)]
    return sorted(
        matches,
        key=lambda report: (_as_utc(report.created_at), report.id),
        reverse=True,
    )


__all__ = ["ReportFilter", "filter_reports", "report_exit_code"]
