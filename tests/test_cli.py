import subprocess
import sys

import pytest
from typer.testing import CliRunner

from repotrace import cli
from repotrace.cli import app
from repotrace.storage import ReportStore

runner = CliRunner()

# A deterministic failing command used across the capture tests.
CMD_FAIL = [sys.executable, "-c", "import sys; print('out'); sys.exit(3)"]
CMD_OK = [sys.executable, "-c", "print('ok')"]

# Keyword name -> CLI flag, used by ``cli_opts`` below.
FLAGS = {
    "tags": "--tags",
    "severity": "--severity",
    "title": "--title",
    "keep_going": "--keep-going",
    "exit_code_only": "--exit-code-only",
    "with_replay": "--replay",
    "no_metadata": "--no-metadata",
    "no_events": "--no-events",
    "overwrite": "--overwrite",
    "function_name": "--name",
    "as_markdown": "--markdown",
    "cwd": "--cwd",
    "timeout": "--timeout",
    "output": "--output",
}


def run(*args: str) -> object:
    """Invoke the CLI with a fresh isolated environment."""
    return runner.invoke(app, list(args), catch_exceptions=False)


def cli_opts(**kwargs) -> list[str]:
    """Turn keyword options into a Typer CLI argv fragment."""
    argv: list[str] = []
    for key, value in kwargs.items():
        flag = FLAGS[key]
        if value is True:
            argv.append(flag)
        else:
            argv.extend([flag, str(value)])
    return argv


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the CLI at an isolated store and return its path."""
    root = tmp_path / "reports"
    monkeypatch.setattr(cli, "DEFAULT_STORE", str(root))
    return root


def capture_report(store, command=None, **kwargs) -> str:
    """Capture a failing command through the CLI and return the report id."""
    result = run(
        "capture",
        "--store",
        str(store),
        *(command or CMD_FAIL),
        *cli_opts(**kwargs),
    )
    assert result.exit_code == 3, result.output
    return result.output.split()[1]


def rewrite_exit_code(store, report_id: str, exit_code: int) -> None:
    """Persist ``report_id`` with a different recorded exit code."""
    store_obj = ReportStore(store)
    stored = store_obj.load(report_id)
    store_obj.save(
        stored.model_copy(
            update={"metadata": dict(stored.metadata, exit_code=exit_code)}
        )
    )


# --- capture ------------------------------------------------------------


def test_capture_persists_report_and_exits_with_command_code(store):
    result = run("capture", "--store", str(store), *CMD_FAIL)

    assert result.exit_code == 3
    report_id = result.output.split()[1]
    assert (store / f"{report_id}.json").exists()
    assert "exit code 3" in result.output


def test_capture_exits_zero_on_success(store):
    result = run("capture", "--store", str(store), *CMD_OK)

    assert result.exit_code == 0
    assert "exit code 0" in result.output


def test_capture_keep_going_masks_failure(store):
    result = run("capture", "--store", str(store), "--keep-going", *CMD_FAIL)

    assert result.exit_code == 0


def test_capture_missing_command_exits_two(store):
    result = run("capture", "--store", str(store), "definitely-not-a-real-binary-xyz")

    assert result.exit_code == 2
    assert "command not found" in result.output


def test_capture_passes_tags_and_severity(store):
    report_id = capture_report(store, tags="flaky,ci", severity="high")

    result = run("show", "--store", str(store), report_id)

    assert "high" in result.output
    assert "flaky, ci" in result.output


def test_capture_defaults_to_hash_id(store):
    first = capture_report(store)
    second = capture_report(store)

    assert first == second
    assert len(first) == 12


def test_capture_accepts_explicit_id(store):
    result = run("capture", "--store", str(store), "--id", "custom-id", *CMD_FAIL)

    assert result.exit_code == 3
    assert "custom-id" in result.output
    assert (store / "custom-id.json").exists()


# --- list / show --------------------------------------------------------


def test_list_reports(store):
    """Two captures of the same command produce one report id (a hash)."""
    first = capture_report(store)
    second = capture_report(store)

    result = run("list", "--store", str(store))

    assert result.exit_code == 0
    assert "1 report(s)" in result.output
    assert first == second


def test_list_reports_empty_store(store):
    result = run("list", "--store", str(store))

    assert result.exit_code == 0
    assert "no reports stored" in result.output


def test_show_prints_fields(store):
    report_id = capture_report(store, title="boom", severity="high")

    result = run("show", "--store", str(store), report_id)

    assert result.exit_code == 0
    assert "boom" in result.output
    assert "high" in result.output
    assert "metadata" in result.output


def test_show_as_markdown(store):
    report_id = capture_report(store)

    result = run("show", "--store", str(store), report_id, "--markdown")

    assert result.exit_code == 0
    assert result.output.startswith("# Capture report:")


def test_show_missing_report_exits_two(store):
    result = run("show", "--store", str(store), "nope")

    assert result.exit_code == 2
    assert "no such report" in result.output


# --- replay -------------------------------------------------------------


def test_replay_matched_reproduces_and_exits_zero(store):
    report_id = capture_report(store)

    result = run("replay", "--store", str(store), report_id)

    assert result.exit_code == 0
    assert "matched" in result.output
    assert "no differences" in result.output
    assert report_id in result.output


def test_replay_differs_exits_one(store):
    report_id = capture_report(store)
    rewrite_exit_code(store, report_id, 0)

    result = run("replay", "--store", str(store), report_id)

    assert result.exit_code == 1
    assert "differs" in result.output
    assert "exit code 0 -> 3" in result.output


def test_replay_keep_going_masks_difference(store):
    report_id = capture_report(store)
    rewrite_exit_code(store, report_id, 0)

    result = run("replay", "--store", str(store), report_id, "--keep-going")

    assert result.exit_code == 0


def test_replay_exit_code_only(store):
    report_id = capture_report(store)

    result = run("replay", "--store", str(store), report_id, "--exit-code-only")

    assert result.exit_code == 0
    assert "matched" in result.output


def test_replay_missing_report_exits_two(store):
    result = run("replay", "--store", str(store), "nope")

    assert result.exit_code == 2


# --- replay-all ---------------------------------------------------------


def test_replay_all_prints_table(store):
    capture_report(store)

    result = run("replay-all", "--store", str(store))

    assert result.exit_code == 0
    assert "Replay summary" in result.output
    assert "reproducibility 100%" in result.output


def test_replay_all_exits_one_when_any_differs(store):
    report_id = capture_report(store)
    rewrite_exit_code(store, report_id, 0)

    result = run("replay-all", "--store", str(store))

    assert result.exit_code == 1
    assert "differs 1" in result.output


def test_replay_all_writes_markdown(store, tmp_path):
    capture_report(store)
    destination = tmp_path / "sweep.md"

    result = run("replay-all", "--store", str(store), "--output", str(destination))

    assert result.exit_code == 0
    assert destination.read_text(encoding="utf-8").startswith("# Replay summary")


def test_replay_all_output_guards_overwrite(store, tmp_path):
    capture_report(store)
    destination = tmp_path / "sweep.md"
    destination.write_text("existing", encoding="utf-8")

    result = run("replay-all", "--store", str(store), "--output", str(destination))

    assert result.exit_code != 0
    assert destination.read_text(encoding="utf-8") == "existing"


def test_replay_all_empty_store(store):
    result = run("replay-all", "--store", str(store))

    assert result.exit_code == 0
    assert "replayed 0" in result.output


# --- report -------------------------------------------------------------


def test_report_prints_markdown(store):
    report_id = capture_report(store)

    result = run("report", "--store", str(store), report_id)

    assert result.exit_code == 0
    assert result.output.startswith("# Capture report:")
    assert "## Events" in result.output


def test_report_with_replay_includes_verdict(store):
    report_id = capture_report(store)

    result = run("report", "--store", str(store), report_id, "--replay")

    assert result.exit_code == 0
    assert "# Replay report — reproduced" in result.output
    assert "## Replay outcome" in result.output


def test_report_writes_file(store, tmp_path):
    report_id = capture_report(store)
    destination = tmp_path / "nested" / "report.md"

    result = run(
        "report", "--store", str(store), report_id, "--output", str(destination)
    )

    assert result.exit_code == 0
    assert destination.read_text(encoding="utf-8").startswith("# Capture report:")
    assert "wrote" in result.output


def test_report_flags_drop_sections(store):
    report_id = capture_report(store)

    result = run(
        "report", "--store", str(store), report_id, "--no-metadata", "--no-events"
    )

    assert "## Metadata" not in result.output
    assert "## Events" not in result.output
    assert "## Summary" in result.output


def test_report_missing_report_exits_two(store):
    result = run("report", "--store", str(store), "nope")

    assert result.exit_code == 2


# --- generate -----------------------------------------------------------


def test_generate_prints_test_source(store):
    report_id = capture_report(store)

    result = run("generate", "--store", str(store), report_id)

    assert result.exit_code == 0
    assert "def test_regression_" in result.output
    assert "assert result.returncode == EXPECTED_EXIT_CODE" in result.output


def test_generate_writes_file(store, tmp_path):
    report_id = capture_report(store)
    destination = tmp_path / "test_generated.py"

    result = run(
        "generate", "--store", str(store), report_id, "--output", str(destination)
    )

    assert result.exit_code == 0
    source = destination.read_text(encoding="utf-8")
    assert source.startswith('"""')
    assert "def test_regression_" in source


def test_generate_writes_a_test_that_passes(store, tmp_path):
    report_id = capture_report(store)
    destination = tmp_path / "test_generated.py"
    run("generate", "--store", str(store), report_id, "--output", str(destination))

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", str(destination), "-q"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_generate_exit_code_only(store):
    report_id = capture_report(store)

    result = run("generate", "--store", str(store), report_id, "--exit-code-only")

    assert "assert result.stdout" not in result.output


def test_generate_missing_report_exits_two(store):
    result = run("generate", "--store", str(store), "nope")

    assert result.exit_code == 2


# --- top level ----------------------------------------------------------


def test_no_args_shows_help():
    result = run()

    assert result.exit_code != 0
    assert "Usage" in result.output


def test_help_lists_commands():
    result = run("--help")

    assert result.exit_code == 0
    for name in (
        "capture",
        "list",
        "show",
        "replay",
        "replay-all",
        "report",
        "generate",
    ):
        assert name in result.output


def test_version_command():
    result = run("version")

    assert result.exit_code == 0
    assert result.output.strip()


def test_main_is_callable():
    assert callable(cli.main)
