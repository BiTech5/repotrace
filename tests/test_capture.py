from datetime import datetime

import pytest
from pydantic import ValidationError

from reprotrace.capture import Trace, TraceEvent, collect_environment


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
