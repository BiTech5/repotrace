import sys
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from reprotrace.capture import Trace, run_capture
from reprotrace.generator import Reproduction
from reprotrace.replay import (
    Outcome,
    ReplayResult,
    diff,
    replay,
    replay_all,
    replay_from_store,
    replay_report,
)
from reprotrace.storage import BugReport, ReportStore


def make_trace(exit_code: int = 2) -> Trace:
    return run_capture(
        [
            sys.executable,
            "-c",
            f"import sys; print('out'); print('err', file=sys.stderr); sys.exit({exit_code})",
        ]
    )


def make_report(
    exit_code: int = 2,
    report_id: str = "reproducible",
    *,
    matches_run: bool = True,
) -> BugReport:
    """Build a report that replays cleanly when ``matches_run`` is true.

    A bare ``python -c ...`` is host independent, and the stdout/stderr events
    recorded alongside the command let the fixture assert a full match rather
    than only an exit code. When ``matches_run`` is false the recorded exit
    code is deliberately wrong, so the replay is expected to differ.
    """
    script = f"import sys; print('out'); print('err', file=sys.stderr); sys.exit({exit_code})"
    recorded_exit = exit_code if matches_run else 0
    return BugReport(
        id=report_id,
        title="replayable failure",
        metadata={
            "command": ["python", "-c", script],
            "exit_code": recorded_exit,
            "cwd": "",
            "events": [
                {
                    "index": 0,
                    "kind": "command",
                    "message": f"python -c {script}",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {"argv": ["python", "-c", script]},
                },
                {
                    "index": 1,
                    "kind": "stdout",
                    "message": "out\n",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {},
                },
                {
                    "index": 2,
                    "kind": "stderr",
                    "message": "err\n",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {},
                },
            ],
        },
    )


def test_outcome_enum_values():
    assert Outcome.MATCHED.value == "matched"
    assert Outcome.DIFFERS.value == "differs"


def test_replay_result_is_frozen():
    result = replay(make_trace())
    with pytest.raises(ValidationError):
        result.outcome = Outcome.DIFFERS


def test_replay_result_defaults_optional_fields():
    """A result built by hand (e.g. by a CLI) still validates cleanly."""
    result = ReplayResult(report_id="", outcome=Outcome.MATCHED)

    assert result.trace is None
    assert result.differences == []
    assert result.stdout == ""
    assert result.report_id == ""
    assert result.matched is True


def test_replay_matched_run(tmp_path):
    trace = make_trace()

    result = replay(trace, cwd=tmp_path)

    assert result.outcome is Outcome.MATCHED
    assert result.matched is True
    assert result.reproducible is True
    assert result.exit_code == 2
    assert result.expected_exit_code == 2
    assert result.differences == []
    assert result.trace is not None


def test_replay_detects_changed_exit_code():
    trace = make_trace(exit_code=2)

    result = replay(Reproduction.from_trace(trace), timeout=None)
    assert result.matched is True

    changed = Reproduction.from_trace(trace).model_copy(update={"exit_code": 0})
    differs = replay(changed)

    assert differs.outcome is Outcome.DIFFERS
    assert differs.matched is False
    assert differs.differences == ["exit code 0 -> 2"]


def test_replay_detects_changed_output():
    trace = make_trace()
    changed = Reproduction.from_trace(trace).model_copy(update={"stdout": "different"})

    result = replay(changed)

    assert result.outcome is Outcome.DIFFERS
    assert "stdout differs" in result.differences


def test_replay_exit_code_only_ignores_output():
    trace = make_trace()
    changed = Reproduction.from_trace(trace).model_copy(update={"stdout": "different"})

    result = replay(changed, match_output=False)

    assert result.outcome is Outcome.MATCHED
    assert result.differences == []


def test_replay_accepts_bug_report():
    result = replay(make_report(exit_code=2))

    assert result.report_id == "reproducible"
    assert result.matched is True


def test_replay_report_replays_recorded_command():
    result = replay_report(make_report(exit_code=3))

    assert result.expected_exit_code == 3
    assert result.exit_code == 3
    assert result.matched is True


def test_replay_report_rejects_report_without_command():
    report = BugReport(id="manual", title="no command")

    with pytest.raises(ValueError, match="does not contain a command"):
        replay_report(report)


def test_replay_from_store(tmp_path):
    store = ReportStore(tmp_path / "reports")
    store.save(make_report(report_id="abc"))

    result = replay_from_store("abc", store)

    assert result.report_id == "abc"
    assert result.matched is True


def test_replay_from_store_missing_report_raises(tmp_path):
    store = ReportStore(tmp_path / "reports")

    with pytest.raises(FileNotFoundError):
        replay_from_store("nope", store)


def test_replay_from_store_preserves_id_when_report_has_none(tmp_path):
    store = ReportStore(tmp_path / "reports")
    store.save(
        BugReport(
            id="manual-entry",
            title="manual",
            metadata={
                "command": [sys.executable, "-c", "print('ok')"],
                "exit_code": 0,
                "events": [
                    {
                        "index": 0,
                        "kind": "command",
                        "message": "python -c print('ok')",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "data": {"argv": [sys.executable, "-c", "print('ok')"]},
                    },
                    {
                        "index": 1,
                        "kind": "stdout",
                        "message": "ok\n",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "data": {},
                    },
                ],
            },
        )
    )

    result = replay_from_store("manual-entry", store)

    assert result.report_id == "manual-entry"
    assert result.matched is True


def test_replay_all_counts_outcomes(tmp_path):
    store = ReportStore(tmp_path / "reports")
    store.save(make_report(report_id="reproducible"))
    store.save(make_report(report_id="changed", matches_run=False))

    summary = replay_all(store)

    assert summary.total == 2
    assert summary.matched == 1
    assert summary.differed == 1
    assert summary.failed == 0
    assert summary.reproducible == pytest.approx(0.5)
    assert [result.report_id for result in summary.results] == [
        "changed",
        "reproducible",
    ]


def test_replay_all_survives_bad_reports(tmp_path):
    store = ReportStore(tmp_path / "reports")
    store.save(make_report(report_id="good"))
    store.save(BugReport(id="empty", title="no command"))

    summary = replay_all(store)

    assert summary.total == 2
    assert summary.matched == 1
    assert summary.failed == 1
    assert [result.report_id for result in summary.results] == ["good"]


def test_replay_all_empty_store():
    summary = replay_all(ReportStore("/tmp/empty-replay-store"))

    assert summary.total == 0
    assert summary.reproducible == 0.0


def test_diff_returns_expected_shape():
    trace = make_trace(exit_code=2)
    changed = Reproduction.from_trace(trace).model_copy(update={"exit_code": 0})
    result = replay(changed)

    payload = diff(result)

    assert payload["report_id"] == ""
    assert payload["outcome"] == "differs"
    assert payload["exit_code"] == {"expected": 0, "observed": 2}
    assert payload["differences"] == ["exit code 0 -> 2"]


def test_replay_from_store_defaults_to_reports_cwd(tmp_path):
    """The recorded cwd is honoured when the caller passes none."""
    recorded_dir = tmp_path / "recorded"
    recorded_dir.mkdir()
    trace = run_capture([sys.executable, "-c", "print('ok')"], cwd=recorded_dir)
    store = ReportStore(tmp_path / "reports")
    store.save(_report_from_trace(trace))

    result = replay_from_store("from-trace", store)

    assert result.cwd == str(recorded_dir)
    assert result.matched is True


def test_replay_rejects_unsupported_source():
    with pytest.raises(TypeError, match="Expected a Reproduction"):
        replay("ls -la")  # type: ignore[arg-type]


def _report_from_trace(trace: Trace) -> BugReport:
    """Wrap ``trace`` in a report whose metadata carries its recorded output."""
    return BugReport(
        id="from-trace",
        title="captured",
        metadata={
            "command": list(trace.command),
            "exit_code": trace.exit_code,
            "cwd": trace.cwd,
            "events": [event.model_dump(mode="json") for event in trace.events],
        },
    )


def test_replay_records_aware_event_timestamps(tmp_path):
    result = replay(make_trace(), cwd=tmp_path)

    assert result.trace is not None
    for event in result.trace.events:
        assert isinstance(event.timestamp, datetime)
        assert event.timestamp.tzinfo is not None
