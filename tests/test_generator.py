import subprocess
import sys

import pytest

from reprotrace.capture import Trace, build_report, run_capture
from reprotrace.generator import (
    Reproduction,
    generate_test,
    slugify,
    write_test,
)
from reprotrace.storage import BugReport


def make_trace() -> Trace:
    return run_capture(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(2)",
        ]
    )


def test_reproduction_from_trace_flattens_output():
    reproduction = Reproduction.from_trace(make_trace(), title="boom")

    assert reproduction.command[0] == sys.executable
    assert reproduction.exit_code == 2
    assert reproduction.stdout.strip() == "out"
    assert reproduction.stderr.strip() == "err"
    assert reproduction.title == "boom"


def test_reproduction_from_report_recovers_command_and_output():
    report = build_report(make_trace(), report_id="fixed")

    reproduction = Reproduction.from_report(report)

    assert reproduction.command == report.metadata["events"][0]["data"]["argv"]
    assert reproduction.exit_code == 2
    assert reproduction.report_id == "fixed"
    assert reproduction.stdout.strip() == "out"


def test_reproduction_from_report_prefers_explicit_command():
    report = BugReport(
        id="explicit",
        title="manual",
        metadata={"command": ["echo", "hi"], "stdout": "ignored"},
    )

    assert Reproduction.from_report(report).command == ["echo", "hi"]


def test_reproduction_from_report_without_command_raises():
    report = BugReport(id="manual", title="no command")

    with pytest.raises(ValueError, match="does not contain a command"):
        Reproduction.from_report(report)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc123", "abc123"),
        ("Command failed: ls -la", "command_failed_ls_la"),
        ("123 start", "case_123_start"),
        ("class", "class_case"),
        ("!!!", "case"),
    ],
)
def test_slugify_produces_identifiers(raw, expected):
    result = slugify(raw, fallback="case")

    assert result == expected
    assert result.isidentifier()


def test_generate_test_includes_assertions_and_compiles():
    source = generate_test(make_trace())

    compile(source, "<generated>", "exec")
    assert "def test_regression_" in source
    assert "assert result.returncode == EXPECTED_EXIT_CODE" in source
    assert "assert result.stdout == EXPECTED_STDOUT" in source
    assert "assert result.stderr == EXPECTED_STDERR" in source


def test_generate_test_accepts_custom_function_name_and_skips_output():
    source = generate_test(
        make_trace(), function_name="test_custom", match_output=False
    )

    assert "def test_custom() -> None:" in source
    assert "EXPECTED_STDOUT" in source
    assert "assert result.stdout" not in source


def test_generate_test_rejects_invalid_function_name():
    with pytest.raises(ValueError, match="Invalid test function name"):
        generate_test(make_trace(), function_name="not a name")


def test_generate_test_requires_command():
    with pytest.raises(ValueError, match="without a command"):
        generate_test(Reproduction(command=[]))


def test_generate_test_rejects_unsupported_source():
    with pytest.raises(TypeError, match="Expected a Reproduction"):
        generate_test("ls -la")  # type: ignore[arg-type]


def test_write_test_writes_file_and_guards_overwrite(tmp_path):
    destination = tmp_path / "nested" / "test_generated.py"

    path = write_test(make_trace(), destination)

    assert path == destination
    assert destination.read_text(encoding="utf-8").startswith('"""')
    with pytest.raises(FileExistsError):
        write_test(make_trace(), destination)

    write_test(make_trace(), destination, overwrite=True)


def test_generated_test_runs_and_passes(tmp_path):
    trace = make_trace()
    destination = write_test(trace, tmp_path / "test_regression_sample.py")

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", str(destination), "-q"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
