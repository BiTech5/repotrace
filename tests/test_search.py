from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from repotrace.search import ReportFilter, filter_reports, report_exit_code
from repotrace.storage import BugReport

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_report(
    report_id: str,
    *,
    title: str = "Sample failure",
    tags: list[str] | None = None,
    severity: str | None = None,
    exit_code: int | None = None,
    created_at: datetime | None = None,
) -> BugReport:
    metadata = {} if exit_code is None else {"exit_code": exit_code}
    return BugReport(
        id=report_id,
        title=title,
        tags=tags or [],
        severity=severity,
        metadata=metadata,
        created_at=created_at or BASE,
    )


@pytest.fixture
def reports() -> list[BugReport]:
    return [
        make_report(
            "a",
            title="Database timeout on startup",
            tags=["flaky", "ci"],
            severity="high",
            exit_code=3,
            created_at=BASE,
        ),
        make_report(
            "b",
            title="CLI rejects --json",
            tags=["cli"],
            severity="low",
            exit_code=1,
            created_at=BASE + timedelta(days=1),
        ),
        make_report(
            "c",
            title="Database migration fails",
            tags=["flaky", "database"],
            severity="high",
            exit_code=2,
            created_at=BASE + timedelta(days=2),
        ),
    ]


def ids(result: list[BugReport]) -> list[str]:
    return [report.id for report in result]


def test_empty_filter_matches_everything_newest_first(reports):
    result = filter_reports(reports, ReportFilter())

    assert ids(result) == ["c", "b", "a"]


def test_filter_by_title_is_case_insensitive_substring(reports):
    result = filter_reports(reports, ReportFilter(title="database"))

    assert ids(result) == ["c", "a"]


def test_filter_by_tags_requires_every_requested_tag(reports):
    assert ids(filter_reports(reports, ReportFilter(tags=("flaky",)))) == ["c", "a"]
    assert ids(filter_reports(reports, ReportFilter(tags=("flaky", "ci")))) == ["a"]
    assert filter_reports(reports, ReportFilter(tags=("missing",))) == []


def test_filter_by_tags_is_case_insensitive(reports):
    result = filter_reports(reports, ReportFilter(tags=("FLAKY",)))

    assert ids(result) == ["c", "a"]


def test_filter_by_severity_is_case_insensitive(reports):
    result = filter_reports(reports, ReportFilter(severity="HIGH"))

    assert ids(result) == ["c", "a"]


def test_filter_by_exit_code(reports):
    result = filter_reports(reports, ReportFilter(exit_code=1))

    assert ids(result) == ["b"]


def test_filter_by_exit_code_excludes_reports_without_one(reports):
    reports.append(make_report("d", title="No exit code"))

    result = filter_reports(reports, ReportFilter(exit_code=0))

    assert result == []


def test_filter_by_date_range_is_inclusive(reports):
    criteria = ReportFilter(
        since=BASE + timedelta(days=1), until=BASE + timedelta(days=2)
    )

    assert ids(filter_reports(reports, criteria)) == ["c", "b"]


def test_filter_combines_every_criterion(reports):
    criteria = ReportFilter(
        title="database",
        tags=("flaky",),
        severity="high",
        exit_code=2,
        since=BASE + timedelta(days=2),
    )

    assert ids(filter_reports(reports, criteria)) == ["c"]


def test_no_match_returns_empty_list(reports):
    result = filter_reports(reports, ReportFilter(title="database", severity="low"))

    assert result == []


def test_naive_bounds_are_treated_as_utc(reports):
    criteria = ReportFilter(
        since=datetime(2026, 1, 2, 12, 0),
        until=datetime(2026, 1, 3, 12, 0),
    )

    assert ids(filter_reports(reports, criteria)) == ["c", "b"]


def test_reverse_date_range_is_rejected():
    with pytest.raises(ValidationError):
        ReportFilter(since=BASE + timedelta(days=1), until=BASE)


def test_report_exit_code_reads_and_coerces_metadata():
    assert report_exit_code(make_report("a", exit_code=3)) == 3
    assert report_exit_code(make_report("a", exit_code=None)) is None

    string_code = BugReport(id="s", title="String", metadata={"exit_code": "7"})
    assert report_exit_code(string_code) == 7

    invalid = BugReport(id="s", title="Invalid", metadata={"exit_code": "nope"})
    assert report_exit_code(invalid) is None
