"""Report rendering for RepoTrace.

Turns a :class:`~repotrace.storage.BugReport` or a
:class:`~repotrace.replay.ReplayResult` / :class:`~repotrace.replay.ReplaySummary`
into inspectable output. Two renderers are provided:

- :func:`format_report` / :func:`write_report` — a self-contained Markdown
  document for one captured failure, with its environment, events, and verdict.
- :func:`format_replays` / :func:`write_replays` — a Markdown table rolling up
  every replay in a sweep.

Rendering is pure string building and never imports the CLI, so these functions
stay usable from scripts and tests. Colour handling is delegated to ``rich``,
which is already a project dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from repotrace.replay import Outcome, ReplayResult, ReplaySummary
from repotrace.storage import BugReport

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


def format_datetime(value: datetime | str | None) -> str:
    """Render a timestamp as a stable, human-readable string.

    Naive timestamps are read as UTC so the output never depends on the host's
    local timezone.

    Args:
        value: A ``datetime``, an ISO-8601 string, or ``None``.

    Returns:
        The formatted timestamp, or an em dash when ``value`` is missing.
    """
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            # Python 3.11+ fromisoformat already understands a trailing "Z".
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime(_DATE_FORMAT)


def format_exit_code(code: int | None) -> str:
    """Render an exit code, marking the success case explicitly."""
    if code is None:
        return "—"
    if code == 0:
        return "0 (success)"
    return str(code)


def escape_cell(text: Any) -> str:
    """Make ``text`` safe to place inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def truncate(text: str, limit: int = 120) -> str:
    """Shorten ``text`` to ``limit`` characters, marking the cut."""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


class ReportSection(BaseModel):
    """One titled block of a rendered report."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(..., description="Heading of the section")
    lines: list[str] = Field(
        default_factory=list, description="Body lines, without the heading"
    )

    def render(self) -> list[str]:
        """Return the heading and body, ending with a blank separator line."""
        return [f"## {self.title}", *self.lines, ""]


def _summary_section(report: BugReport) -> ReportSection:
    """Build the header section describing the report itself."""
    lines = [
        f"**ID:** `{report.id}`",
        f"**Status:** {report.status}",
        f"**Severity:** {report.severity or '—'}",
        f"**Reporter:** {report.reporter or '—'}",
        f"**Assignee:** {report.assignee or '—'}",
        f"**Tags:** {', '.join(report.tags) if report.tags else '—'}",
        f"**Created:** {format_datetime(report.created_at)}",
        f"**Updated:** {format_datetime(report.updated_at)}",
        "",
        report.description or "_No description._",
    ]
    return ReportSection(title="Summary", lines=lines)


def _metadata_section(metadata: dict[str, Any]) -> ReportSection:
    """Render report metadata as a key/value list, dropping empty values."""
    lines: list[str] = []
    for key in sorted(metadata):
        value = metadata[key]
        if value in (None, "", [], {}):
            continue
        rendered = (
            escape_cell(value)
            if isinstance(value, str)
            else f"`{type(value).__name__}`"
        )
        lines.append(f"- **{key}:** {rendered}")
    if not lines:
        lines.append("_No metadata._")
    return ReportSection(title="Metadata", lines=lines)


def _event_field(event: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping or a model, tolerating either form."""
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _events_section(events: Sequence[Any]) -> ReportSection:
    """Render recorded trace events as an indexed listing."""
    lines: list[str] = []
    for event in events:
        index = _event_field(event, "index")
        kind = _event_field(event, "kind", "?")
        message = _event_field(event, "message", "")
        head = f"{index}. `{kind}`" if index is not None else f"`{kind}`"
        lines.append(f"- {head}: {truncate(message.strip(), 200)}")
    if not lines:
        lines.append("_No events recorded._")
    return ReportSection(title="Events", lines=lines)


def outcome_label(outcome: Outcome) -> str:
    """Return a human-readable label for an :class:`Outcome`.

    Args:
        outcome: The verdict to label.

    Returns:
        ``"reproduced"`` or ``"no longer reproduces"``.
    """
    return "reproduced" if outcome is Outcome.MATCHED else "no longer reproduces"


def _command_from_metadata(metadata: dict[str, Any]) -> list[str]:
    """Recover the recorded argv from a report's metadata.

    An explicit ``command`` key wins; otherwise the first ``command`` event's
    ``argv`` is used, which is where :func:`repotrace.capture.build_report`
    records it.
    """
    explicit = metadata.get("command")
    if explicit:
        return [str(part) for part in explicit]
    for event in metadata.get("events", []):
        if _event_field(event, "kind") != "command":
            continue
        data = _event_field(event, "data", {}) or {}
        argv = data.get("argv") if isinstance(data, dict) else None
        if argv:
            return [str(part) for part in argv]
        return str(_event_field(event, "message", "")).split()
    return []


def _replay_lines(report: BugReport, result: ReplayResult) -> list[str]:
    """Build the observed-versus-expected lines for a replay section."""
    command = _command_from_metadata(report.metadata)
    return [
        f"**Outcome:** `{result.outcome.value}` ({outcome_label(result.outcome)})",
        (
            f"**Exit code:** {format_exit_code(result.exit_code)} "
            f"(recorded {format_exit_code(result.expected_exit_code)})"
        ),
        f"**Working directory:** `{result.cwd or '—'}`",
        f"**Command:** `{' '.join(command)}`" if command else "**Command:** —",
        "",
        "Differences: "
        + (", ".join(result.differences) if result.differences else "none"),
    ]


def format_report(
    report: BugReport,
    *,
    result: ReplayResult | None = None,
    include_metadata: bool = True,
    include_events: bool = True,
) -> str:
    """Render a stored bug report as a Markdown document.

    When ``result`` is given, the report is headed as a replay and the observed
    and expected values are compared in a dedicated section, so the same
    function serves both a plain capture report and a post-replay verdict.

    Args:
        report: The report to render.
        result: Optional replay outcome to append and compare against.
        include_metadata: When false, omit the metadata section.
        include_events: When false, omit the event listing.

    Returns:
        The complete Markdown source of the report.
    """
    sections: list[ReportSection] = [_summary_section(report)]

    if result is None:
        heading = f"Capture report: {report.title}"
    else:
        heading = f"Replay report — {outcome_label(result.outcome)}"
        sections.append(
            ReportSection(title="Replay outcome", lines=_replay_lines(report, result))
        )

    if include_metadata:
        sections.append(_metadata_section(report.metadata))
    if include_events:
        sections.append(_events_section(report.metadata.get("events", [])))

    lines = [f"# {heading}", ""]
    for section in sections:
        lines.extend(section.render())
    return "\n".join(lines).rstrip() + "\n"


def write_report(
    report: BugReport,
    path: Path | str,
    *,
    result: ReplayResult | None = None,
    include_metadata: bool = True,
    include_events: bool = True,
    overwrite: bool = False,
) -> Path:
    """Render ``report`` to Markdown and write it to ``path``.

    Args:
        report: The report to render.
        path: Destination file; parent directories are created on demand.
        result: Optional replay outcome, forwarded to :func:`format_report`.
        include_metadata: Forwarded to :func:`format_report`.
        include_events: Forwarded to :func:`format_report`.
        overwrite: When false, refuse to clobber an existing file.

    Returns:
        The path the report was written to.

    Raises:
        FileExistsError: If ``path`` exists and ``overwrite`` is false.
    """
    destination = Path(path)
    if destination.exists() and not overwrite:
        msg = f"{destination} already exists; pass overwrite=True to replace it."
        raise FileExistsError(msg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        format_report(
            report,
            result=result,
            include_metadata=include_metadata,
            include_events=include_events,
        ),
        encoding="utf-8",
    )
    return destination


def _outcome_style(result: ReplayResult) -> str:
    """Pick a colour for ``result`` based on its verdict."""
    return "green" if result.matched else "red"


def render_result_line(result: ReplayResult) -> str:
    """Return a one-line, coloured summary of a single replay.

    Args:
        result: The replay to summarise.

    Returns:
        A Rich markup string suitable for ``rich.print``.
    """
    style = _outcome_style(result)
    label = result.report_id or "(no id)"
    detail = ", ".join(result.differences) if result.differences else "no differences"
    return f"[{style}]{label}[/{style}] `{result.outcome.value}` — {detail}"


def format_replays(summary: ReplaySummary, *, max_rows: int | None = None) -> str:
    """Render a replay sweep as a Markdown table plus a totals block.

    Args:
        summary: The sweep to render.
        max_rows: Optional cap on table rows, for very large stores.

    Returns:
        The Markdown source of the sweep report.
    """
    lines = [
        "# Replay summary",
        "",
        f"**Reports replayed:** {summary.total}",
        f"**Reproduced:** {summary.matched}",
        f"**No longer reproduce:** {summary.differed}",
        f"**Failed to run:** {summary.failed}",
        f"**Reproducibility:** {summary.reproducible:.0%}",
        "",
        "| Report | Outcome | Exit code | Differences |",
        "| --- | --- | --- | --- |",
    ]
    rows = summary.results if max_rows is None else summary.results[:max_rows]
    for result in rows:
        lines.append(
            "| "
            f"`{escape_cell(result.report_id or '—')}` | "
            f"`{escape_cell(result.outcome.value)}` | "
            f"{escape_cell(format_exit_code(result.exit_code))} | "
            f"{escape_cell(', '.join(result.differences) or 'none')} |"
        )
    if max_rows is not None and len(summary.results) > max_rows:
        hidden = len(summary.results) - max_rows
        lines.append(f"| … | … | … | {hidden} more not shown |")
    return "\n".join(lines) + "\n"


def write_replays(
    summary: ReplaySummary,
    path: Path | str,
    *,
    max_rows: int | None = None,
    overwrite: bool = False,
) -> Path:
    """Render a replay sweep to Markdown and write it to ``path``.

    Args:
        summary: The sweep to render.
        path: Destination file; parent directories are created on demand.
        max_rows: Forwarded to :func:`format_replays`.
        overwrite: When false, refuse to clobber an existing file.

    Returns:
        The path the report was written to.

    Raises:
        FileExistsError: If ``path`` exists and ``overwrite`` is false.
    """
    destination = Path(path)
    if destination.exists() and not overwrite:
        msg = f"{destination} already exists; pass overwrite=True to replace it."
        raise FileExistsError(msg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(format_replays(summary, max_rows=max_rows), encoding="utf-8")
    return destination


def build_summary(
    total: int = 0,
    matched: int = 0,
    differed: int = 0,
    failed: int = 0,
    results: Sequence[ReplayResult] | None = None,
) -> ReplaySummary:
    """Build a :class:`ReplaySummary` from raw counts.

    Provided for callers that already hold counts, such as a CLI that streams
    replays instead of collecting them first.

    Args:
        total: Number of replays attempted.
        matched: Number that reproduced.
        differed: Number that changed.
        failed: Number that raised.
        results: Optional individual results to attach.

    Returns:
        A validated :class:`ReplaySummary`.
    """
    return ReplaySummary(
        total=total,
        matched=matched,
        differed=differed,
        failed=failed,
        results=list(results or []),
    )
