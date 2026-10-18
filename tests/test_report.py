import sys
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from repotrace.capture import run_capture
from repotrace.replay import Outcome, ReplayResult, ReplaySummary
from repotrace.report import (
    ReportSection,
    build_summary,
    escape_cell,
    format_datetime,
    format_exit_code,
    format_replays,
    format_report,
    outcome_label,
    render_result_line,
    truncate,
    write_replays,
    write_report,
)
from repotrace.storage import BugReport


def make_report(report_id: str = "abc123", **kwargs) -> BugReport:
    data = {"id": report_id, "title": "Command failed: boom"}
    data.update(kwargs)
    return BugReport(**data)


def make_replay(
    report_id: str = "abc123",
    outcome: Outcome = Outcome.MATCHED,
    **kwargs,
) -> ReplayResult:
    data = {"report_id": report_id, "outcome": outcome}
    data.update(kwargs)
    return ReplayResult(**data)


def make_captured_report(tmp_path) -> BugReport:
    """Capture a real failing run and return the report it produced."""
    trace = run_capture(
        [sys.executable, "-c", "import sys; print('out'); sys.exit(2)"], cwd=tmp_path
    )
    return BugReport(
        id="captured",
        title="Command failed",
        severity="high",
        tags=["capture"],
        metadata={
            "command": list(trace.command),
            "exit_code": trace.exit_code,
            "cwd": trace.cwd,
            "events": [event.model_dump(mode="json") for event in trace.events],
        },
    )


# --- formatting helpers -------------------------------------------------


def test_format_datetime_accepts_aware_naive_and_string():
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    naive = datetime(2026, 1, 2, 3, 4, 5)

    assert format_datetime(aware) == "2026-01-02 03:04:05 UTC"
    assert format_datetime(naive) == "2026-01-02 03:04:05 UTC"
    assert format_datetime("2026-01-02T03:04:05Z") == "2026-01-02 03:04:05 UTC"


def test_format_datetime_converts_between_timezones():
    # 23:30 in a UTC+05:45 zone is 17:45 UTC on the same day.
    zone = timezone(timedelta(hours=5, minutes=45))
    local = datetime(2026, 1, 2, 23, 30, tzinfo=zone)

    assert format_datetime(local) == "2026-01-02 17:45:00 UTC"


def test_format_datetime_handles_none_and_garbage():
    assert format_datetime(None) == "—"
    assert format_datetime("not a date") == "not a date"


def test_format_exit_code_marks_success():
    assert format_exit_code(0) == "0 (success)"
    assert format_exit_code(7) == "7"
    assert format_exit_code(None) == "—"


def test_escape_cell_escapes_pipes_and_newlines():
    assert escape_cell("a|b") == "a\\|b"
    assert escape_cell("line\nbreak") == "line break"
    assert escape_cell(42) == "42"


def test_truncate_marks_the_cut():
    assert truncate("short") == "short"
    assert truncate("x" * 200, limit=10) == "x" * 9 + "…"
    assert len(truncate("x" * 200, limit=10)) == 10


def test_report_section_renders_heading_and_separator():
    section = ReportSection(title="Events", lines=["- one"])

    assert section.render() == ["## Events", "- one", ""]


def test_outcome_label():
    assert outcome_label(Outcome.MATCHED) == "reproduced"
    assert outcome_label(Outcome.DIFFERS) == "no longer reproduces"


# --- report rendering ---------------------------------------------------


def test_format_report_contains_summary_and_heading():
    report = make_report(severity="high", reporter="ada", description="it broke")

    rendered = format_report(report)

    assert rendered.startswith("# Capture report: Command failed: boom\n")
    assert "**Severity:** high" in rendered
    assert "**Reporter:** ada" in rendered
    assert "it broke" in rendered
    assert "**ID:** `abc123`" in rendered


def test_format_report_marks_missing_optional_fields():
    rendered = format_report(make_report())

    assert "**Severity:** —" in rendered
    assert "**Description" not in rendered
    assert "_No description._" in rendered


def test_format_report_with_replay_result_compares_values(tmp_path):
    report = make_captured_report(tmp_path)
    result = make_replay(
        report_id="captured",
        exit_code=2,
        expected_exit_code=2,
        stdout="out\n",
        expected_stdout="out\n",
        cwd=str(tmp_path),
    )

    rendered = format_report(report, result=result)

    assert rendered.startswith("# Replay report — reproduced\n")
    assert "**Outcome:** `matched` (reproduced)" in rendered
    assert "**Exit code:** 2 (recorded 2)" in rendered
    assert "Differences: none" in rendered


def test_format_report_flagged_when_replay_differs(tmp_path):
    report = make_captured_report(tmp_path)
    result = make_replay(
        report_id="captured",
        outcome=Outcome.DIFFERS,
        exit_code=2,
        expected_exit_code=0,
        differences=["exit code 0 -> 2"],
    )

    rendered = format_report(report, result=result)

    assert rendered.startswith("# Replay report — no longer reproduces\n")
    assert "Differences: exit code 0 -> 2" in rendered
    assert "**Exit code:** 2 (recorded 0 (success))" in rendered


def test_format_report_renders_events(tmp_path):
    report = make_captured_report(tmp_path)

    rendered = format_report(report)

    assert "## Events" in rendered
    assert "`command`" in rendered
    assert "`exit`" in rendered
    assert "`stdout`" in rendered


def test_format_report_renders_events_as_models(tmp_path):
    """Events may be ``TraceEvent`` models as well as serialised dicts."""
    trace = run_capture(
        [sys.executable, "-c", "import sys; print('x'); sys.exit(1)"], cwd=tmp_path
    )
    report = BugReport(
        id="models",
        title="model events",
        metadata={"command": list(trace.command), "events": list(trace.events)},
    )

    rendered = format_report(report)

    assert "0. `command`" in rendered
    assert "1. `stdout`" in rendered


def test_format_report_recovers_command_from_events(tmp_path):
    """A report without a top-level command key still shows its argv."""
    report = make_captured_report(tmp_path)
    result = make_replay(report_id="captured")

    rendered = format_report(report, result=result)

    assert "**Command:** `" in rendered
    assert "-c" in rendered


def test_format_report_prefers_explicit_command_key(tmp_path):
    report = make_captured_report(tmp_path)
    report = report.model_copy(
        update={"metadata": dict(report.metadata, command=["echo", "explicit"])}
    )

    rendered = format_report(report, result=make_replay())

    assert "**Command:** `echo explicit`" in rendered


def test_format_report_without_command_shows_placeholder(tmp_path):
    report = make_captured_report(tmp_path).model_copy(update={"metadata": {}})

    rendered = format_report(report, result=make_replay())

    assert "**Command:** —" in rendered


def test_format_report_can_drop_metadata_and_events(tmp_path):
    report = make_captured_report(tmp_path)

    rendered = format_report(report, include_metadata=False, include_events=False)

    assert "## Metadata" not in rendered
    assert "## Events" not in rendered
    assert "## Summary" in rendered


def test_format_report_without_events_notes_it(tmp_path):
    report = make_captured_report(tmp_path).model_copy(update={"metadata": {}})

    rendered = format_report(report)

    assert "_No events recorded._" in rendered


def test_format_report_metadata_skips_empty_values():
    report = make_report(metadata={"exit_code": 2, "cwd": "", "events": []})

    rendered = format_report(report)

    assert "**exit_code:**" in rendered
    assert "**cwd:**" not in rendered


def test_format_report_metadata_handles_non_string_values():
    report = make_report(metadata={"exit_code": 2, "environment": {"python": "3.12"}})

    rendered = format_report(report)

    assert "**exit_code:** `int`" in rendered
    assert "**environment:** `dict`" in rendered


def test_write_report_writes_and_guards_overwrite(tmp_path):
    report = make_report()
    destination = tmp_path / "nested" / "report.md"

    path = write_report(report, destination)

    assert path == destination
    assert destination.read_text(encoding="utf-8").startswith("# Capture report:")
    with pytest.raises(FileExistsError):
        write_report(report, destination)
    write_report(report, destination, overwrite=True)


def test_write_report_forwards_replay_result(tmp_path):
    report = make_captured_report(tmp_path)
    result = make_replay(report_id="captured")

    destination = write_report(report, tmp_path / "out" / "report.md", result=result)

    assert "Replay outcome" in destination.read_text(encoding="utf-8")


# --- replay sweep rendering ---------------------------------------------


def test_format_replays_renders_totals_and_rows():
    summary = build_summary(
        total=2,
        matched=1,
        differed=1,
        results=[
            make_replay("one", Outcome.MATCHED, exit_code=2),
            make_replay(
                "two", Outcome.DIFFERS, exit_code=2, differences=["exit code 0 -> 2"]
            ),
        ],
    )

    rendered = format_replays(summary)

    assert rendered.startswith("# Replay summary")
    assert "**Reports replayed:** 2" in rendered
    assert "**Reproduced:** 1" in rendered
    assert "**No longer reproduce:** 1" in rendered
    assert "**Reproducibility:** 50%" in rendered
    assert "| `one` | `matched` | 2 | none |" in rendered
    assert "| `two` | `differs` | 2 | exit code 0 -> 2 |" in rendered


def test_format_replays_handles_empty_summary():
    rendered = format_replays(build_summary())

    assert "**Reports replayed:** 0" in rendered
    assert "**Reproducibility:** 0%" in rendered
    assert "| Report | Outcome | Exit code | Differences |" in rendered


def test_format_replays_caps_rows():
    results = [make_replay(f"r{i}") for i in range(5)]
    summary = build_summary(total=5, matched=5, results=results)

    rendered = format_replays(summary, max_rows=2)

    assert "| `r0` |" in rendered
    assert "| `r4` |" not in rendered
    assert "3 more not shown" in rendered


def test_write_replays_writes_and_guards_overwrite(tmp_path):
    summary = build_summary(total=1, matched=1, results=[make_replay("one")])
    destination = tmp_path / "sweep" / "summary.md"

    path = write_replays(summary, destination)

    assert path == destination
    assert "Replay summary" in destination.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_replays(summary, destination)
    write_replays(summary, destination, overwrite=True)


def test_render_result_line_colours_by_outcome():
    matched = render_result_line(make_replay("m", Outcome.MATCHED))
    differs = render_result_line(
        make_replay("d", Outcome.DIFFERS, differences=["exit code 0 -> 2"])
    )

    assert "[green]m[/green]" in matched
    assert "[red]d[/red]" in differs
    assert "no differences" in matched
    assert "exit code 0 -> 2" in differs


def test_render_result_line_falls_back_when_report_id_missing():
    assert "(no id)" in render_result_line(make_replay(""))


def test_build_summary_defaults_and_validates():
    empty = build_summary()
    assert empty.total == 0
    assert empty.reproducible == 0.0

    built = build_summary(total=3, matched=2, differed=1, results=[make_replay("x")])
    assert isinstance(built, ReplaySummary)
    assert built.reproducible == pytest.approx(2 / 3)


def test_report_section_is_frozen():
    section = ReportSection(title="Summary")
    with pytest.raises(ValidationError):
        section.title = "changed"
