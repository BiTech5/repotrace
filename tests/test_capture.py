import sys
from datetime import datetime

import pytest
from pydantic import ValidationError

from reprotrace.capture import (
    Trace,
    TraceEvent,
    build_report,
    capture_command,
    collect_environment,
    run_capture,
)
from reprotrace.storage import ReportStore


def test_trace_event_is_frozen():
    event = TraceEvent(index=0, kind="command", message="ls")
    with pytest.raises(ValidationError):
        event.message = "changed"


def test_trace_event_timestamp_is_aware():
    event = TraceEvent(index=0, kind="exit", message="done")
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo is not None


def test_collect_environment_reports_interpreter_and_cwd(tmp_path):
    env = collect_environment(tmp_path)

    assert env["cwd"] == str(tmp_path)
    assert env["executable"]
    assert env["python_version"]
    assert env["platform"]


def test_collect_environment_defaults_to_process_cwd():
    assert collect_environment()["cwd"]


def test_trace_start_records_command_event(tmp_path):
    trace = Trace.start(["echo", "hi"], cwd=tmp_path)

    assert trace.command == ["echo", "hi"]
    assert trace.cwd == str(tmp_path)
    assert trace.exit_code is None
    assert trace.environment["cwd"] == str(tmp_path)
    assert [event.kind for event in trace.events] == ["command"]
    assert trace.events[0].data["argv"] == ["echo", "hi"]


def test_trace_add_appends_ordered_events():
    trace = Trace.start(["ls"])
    trace = trace.add(kind="stdout", message="a").add(kind="exit", message="0")

    assert [event.index for event in trace.events] == [0, 1, 2]
    assert [event.kind for event in trace.events] == ["command", "stdout", "exit"]


def test_trace_add_does_not_mutate_original():
    trace = Trace.start(["ls"])
    trace.add(kind="stdout", message="a")

    assert len(trace.events) == 1


def test_trace_of_kind_filters_events():
    trace = Trace.start(["ls"]).add(kind="stderr", message="boom")

    assert len(trace.of_kind("command")) == 1
    assert [event.message for event in trace.of_kind("stderr")] == ["boom"]
    assert trace.of_kind("missing") == []


def test_run_capture_records_stdout_stderr_and_exit_code(tmp_path):
    script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"

    trace = run_capture([sys.executable, "-c", script], cwd=tmp_path)

    assert trace.exit_code == 3
    assert [event.kind for event in trace.events] == [
        "command",
        "stdout",
        "stderr",
        "exit",
    ]
    assert trace.of_kind("stdout")[0].message.strip() == "out"
    assert trace.of_kind("stderr")[0].message.strip() == "err"


def test_run_capture_records_success(tmp_path):
    trace = run_capture([sys.executable, "-c", "print('hi')"], cwd=tmp_path)

    assert trace.exit_code == 0
    assert trace.of_kind("stderr") == []


def test_build_report_from_failing_trace(tmp_path):
    trace = run_capture([sys.executable, "-c", "raise SystemExit(1)"], cwd=tmp_path)

    report = build_report(trace, severity="high")

    assert report.severity == "high"
    assert report.title == f"Command failed: {sys.executable} -c raise SystemExit(1)"
    assert report.tags == ["capture"]
    assert report.metadata["exit_code"] == 1
    assert report.metadata["cwd"] == str(tmp_path)
    assert len(report.metadata["events"]) == len(trace.events)


def test_build_report_defaults_id_to_command_hash():
    trace = Trace.start(["echo", "hi"])

    first = build_report(trace)
    second = build_report(trace)

    assert first.id == second.id
    assert len(first.id) == 12


def test_build_report_accepts_overrides():
    trace = Trace.start(["ls"])
    report = build_report(trace, title="Custom", report_id="fixed")

    assert report.id == "fixed"
    assert report.title == "Custom"


def test_capture_command_saves_report_when_store_given(tmp_path):
    store = ReportStore(tmp_path / "reports")

    trace, report = capture_command([sys.executable, "-c", "print('ok')"], store=store)

    assert trace.exit_code == 0
    assert store.exists(report.id)
    assert store.load(report.id).metadata["exit_code"] == 0


def test_capture_command_without_store_returns_unsaved_report(tmp_path):
    trace, report = capture_command([sys.executable, "-c", "print('ok')"])

    assert trace.exit_code == 0
    assert report.id
