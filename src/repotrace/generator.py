"""Regression test generation for RepoTrace.

Turns a captured failure — either a :class:`~reprotrace.storage.BugReport`
produced by :mod:`reprotrace.capture` or a raw
:class:`~reprotrace.capture.Trace` — into a standalone ``pytest`` test that
re-runs the recorded command and asserts the original failure signature
(exit code and captured output) has not changed.

The generated test is intentionally self-contained: it embeds the command and
expected output as literals so it can be committed next to the project and run
without RepoTrace installed.
"""

from __future__ import annotations

import keyword
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reprotrace.capture import Trace
from reprotrace.storage import BugReport

_MAX_NAME_LENGTH = 60


class Reproduction(BaseModel):
    """Normalised description of a failure used as generator input.

    A ``Reproduction`` flattens the differences between a raw
    :class:`~reprotrace.capture.Trace` and the metadata embedded in a
    :class:`~reprotrace.storage.BugReport` so that test generation only has to
    deal with a single shape.
    """

    model_config = ConfigDict(frozen=True)

    command: list[str] = Field(..., description="Argv of the recorded command")
    cwd: str = Field(default="", description="Working directory of the run")
    exit_code: int | None = Field(
        default=None, description="Exit code recorded for the run"
    )
    stdout: str = Field(default="", description="Standard output captured")
    stderr: str = Field(default="", description="Standard error captured")
    report_id: str | None = Field(default=None, description="Source report id")
    title: str = Field(default="", description="Human readable failure summary")

    @classmethod
    def from_trace(
        cls,
        trace: Trace,
        *,
        report_id: str | None = None,
        title: str = "",
    ) -> Reproduction:
        """Build a reproduction from a captured :class:`Trace`."""
        return cls(
            command=list(trace.command),
            cwd=trace.cwd,
            exit_code=trace.exit_code,
            stdout="".join(event.message for event in trace.of_kind("stdout")),
            stderr="".join(event.message for event in trace.of_kind("stderr")),
            report_id=report_id,
            title=title,
        )

    @classmethod
    def from_report(cls, report: BugReport) -> Reproduction:
        """Build a reproduction from a persisted :class:`BugReport`.

        The command and output are recovered from ``report.metadata`` as written
        by :func:`reprotrace.capture.build_report`. An explicit ``command`` key
        takes precedence over the command event when present.

        Raises:
            ValueError: If the report carries no usable command.
        """
        metadata = report.metadata or {}
        events = metadata.get("events", [])
        command = list(metadata.get("command") or _command_from_events(events))
        if not command:
            msg = (
                f"Report {report.id!r} does not contain a command; it was "
                "probably not produced by reprotrace.capture."
            )
            raise ValueError(msg)
        return cls(
            command=command,
            cwd=str(metadata.get("cwd") or ""),
            exit_code=metadata.get("exit_code"),
            stdout=_join_messages(events, "stdout"),
            stderr=_join_messages(events, "stderr"),
            report_id=report.id,
            title=report.title,
        )


def _field(event: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping or model, tolerating either representation."""
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _command_from_events(events: list[Any]) -> list[str]:
    """Return the argv recorded in the first ``command`` event, if any."""
    for event in events:
        if _field(event, "kind") != "command":
            continue
        data = _field(event, "data", {}) or {}
        argv = data.get("argv") if isinstance(data, dict) else None
        if argv:
            return list(argv)
        return str(_field(event, "message", "")).split()
    return []


def _join_messages(events: list[Any], kind: str) -> str:
    """Concatenate the messages of every event with ``kind`` in order."""
    return "".join(
        str(_field(event, "message", ""))
        for event in events
        if _field(event, "kind") == kind
    )


def slugify(text: str, *, fallback: str = "case") -> str:
    """Convert ``text`` into a valid, lowercase Python identifier fragment."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    slug = slug[:_MAX_NAME_LENGTH].strip("_")
    if not slug:
        slug = fallback
    if slug[0].isdigit():
        slug = f"case_{slug}"
    if keyword.iskeyword(slug):
        slug = f"{slug}_case"
    return slug


def _as_reproduction(
    source: Reproduction | Trace | BugReport,
) -> Reproduction:
    """Coerce supported inputs into a :class:`Reproduction`."""
    if isinstance(source, Reproduction):
        return source
    if isinstance(source, Trace):
        return Reproduction.from_trace(source)
    if isinstance(source, BugReport):
        return Reproduction.from_report(source)
    msg = f"Expected a Reproduction, Trace, or BugReport, got {type(source).__name__}"
    raise TypeError(msg)


def _default_function_name(reproduction: Reproduction) -> str:
    """Derive a stable test function name from the reproduction source."""
    seed = reproduction.report_id or "captured"
    return f"test_regression_{slugify(seed, fallback='captured')}"


def _docstring(text: str) -> str:
    """Make ``text`` safe to embed inside a triple-quoted docstring."""
    return text.replace("\\", "\\\\").replace('"""', "'''").replace("\n", " ")


def generate_test(
    source: Reproduction | Trace | BugReport,
    *,
    function_name: str | None = None,
    match_output: bool = True,
) -> str:
    """Render a standalone ``pytest`` regression test for ``source``.

    The generated module re-runs the recorded argv and asserts the exit code,
    plus stdout/stderr when ``match_output`` is true.

    Args:
        source: A :class:`Reproduction`, :class:`Trace`, or :class:`BugReport`.
        function_name: Explicit test function name; defaults to one derived
            from the report id.
        match_output: When false, only the exit code is asserted. Useful when
            the captured output contains machine-specific paths.

    Returns:
        The complete source of a pytest test module.

    Raises:
        ValueError: If the source does not describe a runnable command.
        TypeError: If ``source`` is of an unsupported type.
    """
    reproduction = _as_reproduction(source)
    if not reproduction.command:
        msg = "Cannot generate a test without a command to reproduce."
        raise ValueError(msg)
    name = function_name or _default_function_name(reproduction)
    if not name.isidentifier():
        msg = f"Invalid test function name: {name!r}"
        raise ValueError(msg)

    summary = reproduction.title or " ".join(reproduction.command)
    command_line = " ".join(reproduction.command)
    lines = [
        '"""Regression test generated by RepoTrace.',
        "",
        f"Report: {_docstring(reproduction.report_id or 'n/a')}",
        f"Title: {_docstring(summary)}",
        f"Recorded command: {_docstring(command_line)}",
        f"Recorded cwd: {_docstring(reproduction.cwd or 'n/a')}",
        f"Recorded exit code: {reproduction.exit_code}",
        '"""',
        "",
        "import subprocess",
        "",
        f"COMMAND = {reproduction.command!r}",
        f"EXPECTED_EXIT_CODE = {reproduction.exit_code!r}",
        f"EXPECTED_STDOUT = {reproduction.stdout!r}",
        f"EXPECTED_STDERR = {reproduction.stderr!r}",
        "",
        "",
        f"def {name}() -> None:",
        "    result = subprocess.run(COMMAND, capture_output=True, text=True)",
        "",
        "    assert result.returncode == EXPECTED_EXIT_CODE",
    ]
    if match_output:
        lines.append("    assert result.stdout == EXPECTED_STDOUT")
        lines.append("    assert result.stderr == EXPECTED_STDERR")
    lines.append("")
    return "\n".join(lines)


def write_test(
    source: Reproduction | Trace | BugReport,
    path: Path | str,
    *,
    function_name: str | None = None,
    match_output: bool = True,
    overwrite: bool = False,
) -> Path:
    """Generate a regression test and write it to ``path``.

    Args:
        source: Forwarded to :func:`generate_test`.
        path: Destination file; parent directories are created on demand.
        function_name: Forwarded to :func:`generate_test`.
        match_output: Forwarded to :func:`generate_test`.
        overwrite: When false, refuse to clobber an existing file.

    Returns:
        The path the test was written to.

    Raises:
        FileExistsError: If ``path`` exists and ``overwrite`` is false.
    """
    destination = Path(path)
    if destination.exists() and not overwrite:
        msg = f"{destination} already exists; pass overwrite=True to replace it."
        raise FileExistsError(msg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        generate_test(
            source,
            function_name=function_name,
            match_output=match_output,
        ),
        encoding="utf-8",
    )
    return destination
