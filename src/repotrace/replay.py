"""Replay layer for RepoTrace.

Re-runs the command recorded in a stored bug report and compares the fresh
outcome against the one that was captured. A replay either *matches* (the
failure still reproduces) or *differs*, in which case the new exit code and
output are returned so the caller can decide whether to update the report or
open one instead.

A replay is self-contained: it needs nothing but the stored report, the
reproducer, and a working directory.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reprotrace.capture import Trace, run_capture
from reprotrace.generator import Reproduction
from reprotrace.storage import BugReport, ReportStore


class Outcome(str, Enum):
    """Verdict of a replay when compared against the recorded failure."""

    MATCHED = "matched"
    DIFFERS = "differs"


class ReplayResult(BaseModel):
    """Outcome of re-running a recorded command."""

    model_config = ConfigDict(frozen=True)

    report_id: str = Field(..., description="Identifier of the replayed report")
    outcome: Outcome = Field(..., description="Whether the run matched the record")
    exit_code: int | None = Field(
        None, description="Exit code observed during the replay"
    )
    expected_exit_code: int | None = Field(
        None, description="Exit code recorded in the report"
    )
    stdout: str = Field(default="", description="Standard output captured")
    stderr: str = Field(default="", description="Standard error captured")
    expected_stdout: str = Field(default="", description="Standard output recorded")
    expected_stderr: str = Field(default="", description="Standard error recorded")
    cwd: str = Field(default="", description="Working directory of the replay")
    timeout: float | None = Field(
        None, description="Timeout applied to the replay, if any"
    )
    differences: list[str] = Field(
        default_factory=list,
        description="Human readable list of fields that changed",
    )
    trace: Trace | None = Field(
        default=None, description="Raw trace produced by the replay"
    )

    @property
    def matched(self) -> bool:
        """Whether the replay reproduced the recorded failure."""
        return self.outcome is Outcome.MATCHED

    @property
    def reproducible(self) -> bool:
        """Alias of :attr:`matched` for readers that prefer the term."""
        return self.matched


class ReplaySummary(BaseModel):
    """Roll-up of several replays, e.g. a whole report store."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(default=0, description="Number of replays attempted")
    matched: int = Field(default=0, description="Replays that matched the record")
    differed: int = Field(default=0, description="Replays that changed")
    failed: int = Field(
        default=0,
        description="Replays that raised, e.g. a report without a usable command",
    )
    results: list[ReplayResult] = Field(
        default_factory=list, description="Individual replay results"
    )

    @property
    def reproducible(self) -> float:
        """Share of attempted replays that reproduced, from 0.0 to 1.0."""
        return self.matched / self.total if self.total else 0.0


def _as_reproduction(source: Reproduction | Trace | BugReport) -> Reproduction:
    """Coerce ``source`` into a :class:`Reproduction`.

    Raises:
        TypeError: If ``source`` is of an unsupported type.
    """
    if isinstance(source, Reproduction):
        return source
    if isinstance(source, Trace):
        return Reproduction.from_trace(source)
    if isinstance(source, BugReport):
        return Reproduction.from_report(source)
    msg = f"Expected a Reproduction, Trace, or BugReport, got {type(source).__name__}"
    raise TypeError(msg)


def replay(
    source: Reproduction | Trace | BugReport,
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    match_output: bool = True,
) -> ReplayResult:
    """Re-run a recorded command and compare it with the original failure.

    The recorded command is executed again in ``cwd`` (the report's own
    working directory by default) and the fresh exit code and output are
    compared against the recorded ones. The comparison is strict when
    ``match_output`` is true and exit-code-only otherwise.

    Args:
        source: A :class:`Reproduction`, :class:`Trace`, or :class:`BugReport`.
        cwd: Working directory to replay in; defaults to the recorded one.
        timeout: Seconds to wait before the process is killed.
        match_output: When false, only the exit code is compared.

    Returns:
        A frozen :class:`ReplayResult` carrying the verdict, the observed and
        expected values, and the raw :class:`Trace`.

    Raises:
        TypeError: If ``source`` is of an unsupported type.
    """
    reproduction = _as_reproduction(source)
    workdir = Path(cwd) if cwd is not None else Path(reproduction.cwd or ".")
    trace = run_capture(reproduction.command, cwd=workdir, timeout=timeout)

    expected_stdout = reproduction.stdout or ""
    expected_stderr = reproduction.stderr or ""
    stdout = "".join(event.message for event in trace.of_kind("stdout"))
    stderr = "".join(event.message for event in trace.of_kind("stderr"))
    differences: list[str] = []

    if reproduction.exit_code is not None and trace.exit_code != reproduction.exit_code:
        differences.append(f"exit code {reproduction.exit_code} -> {trace.exit_code}")
    if match_output and stdout != expected_stdout:
        differences.append("stdout differs")
    if match_output and stderr != expected_stderr:
        differences.append("stderr differs")

    return ReplayResult(
        report_id=reproduction.report_id or "",
        outcome=Outcome.DIFFERS if differences else Outcome.MATCHED,
        exit_code=trace.exit_code,
        expected_exit_code=reproduction.exit_code,
        stdout=stdout,
        expected_stdout=expected_stdout,
        stderr=stderr,
        expected_stderr=expected_stderr,
        cwd=trace.cwd,
        timeout=timeout,
        differences=differences,
        trace=trace,
    )


def replay_report(
    report: BugReport,
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    match_output: bool = True,
) -> ReplayResult:
    """Replay a stored report by re-running its recorded command.

    Args:
        report: The report whose recorded command should be re-run.
        cwd: Working directory to replay in; defaults to the recorded one.
        timeout: Seconds to wait before the process is killed.
        match_output: When false, only the exit code is compared.

    Returns:
        The :class:`ReplayResult` for the replay.

    Raises:
        ValueError: If the report carries no usable command.
    """
    return replay(
        Reproduction.from_report(report),
        cwd=cwd,
        timeout=timeout,
        match_output=match_output,
    )


def replay_from_store(
    report_id: str,
    store: ReportStore,
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    match_output: bool = True,
) -> ReplayResult:
    """Load ``report_id`` from ``store`` and replay it.

    Args:
        report_id: Identifier of the stored report to replay.
        store: Store the report is loaded from.
        cwd: Working directory to replay in; defaults to the recorded one.
        timeout: Seconds to wait before the process is killed.
        match_output: When false, only the exit code is compared.

    Returns:
        The :class:`ReplayResult` for the replay.

    Raises:
        FileNotFoundError: If ``store`` has no report with ``report_id``.
    """
    report = store.load(report_id)
    result = replay_report(report, cwd=cwd, timeout=timeout, match_output=match_output)
    # Preserve the true identifier even when the report carries none.
    return (
        result
        if result.report_id
        else result.model_copy(update={"report_id": report_id})
    )


def replay_all(
    store: ReportStore,
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    match_output: bool = True,
) -> ReplaySummary:
    """Replay every report in ``store`` and summarise the outcomes.

    Reports that raise — for example a report without a usable command — are
    counted as failures rather than aborting the sweep, so one malformed report
    does not hide the rest of the results.

    Args:
        store: Store whose reports should be replayed.
        cwd: Working directory to replay in; defaults to each recorded one.
        timeout: Seconds to wait before each process is killed.
        match_output: When false, only exit codes are compared.

    Returns:
        A :class:`ReplaySummary` with per-report results and totals.

    Raises:
        FileNotFoundError: If a report disappears from ``store`` between listing
            and loading it. Nothing is raised for reports that fail to replay.
    """
    results: list[ReplayResult] = []
    failed = 0
    for report_id in store.list_ids():
        try:
            results.append(
                replay_from_store(
                    report_id,
                    store,
                    cwd=cwd,
                    timeout=timeout,
                    match_output=match_output,
                )
            )
        except (ValueError, TypeError, OSError):
            failed += 1
    matched = sum(1 for result in results if result.matched)
    return ReplaySummary(
        total=len(results) + failed,
        matched=matched,
        differed=len(results) - matched,
        failed=failed,
        results=results,
    )


def diff(result: ReplayResult) -> dict[str, Any]:
    """Return the recorded-versus-observed values for a replay result.

    Args:
        result: A replay result to summarise.

    Returns:
        A JSON-serialisable mapping of the fields that are compared.
    """
    return {
        "report_id": result.report_id,
        "outcome": result.outcome.value,
        "exit_code": {
            "expected": result.expected_exit_code,
            "observed": result.exit_code,
        },
        "stdout": {"expected": result.expected_stdout, "observed": result.stdout},
        "stderr": {"expected": result.expected_stderr, "observed": result.stderr},
        "differences": list(result.differences),
    }
