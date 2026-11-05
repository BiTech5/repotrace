from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.table import Table

from repotrace.capture import capture_command
from repotrace.generator import generate_test, write_test
from repotrace.replay import (
    Outcome,
    ReplayResult,
    ReplaySummary,
    replay_all,
    replay_from_store,
)
from repotrace.report import (
    build_summary,
    format_datetime,
    format_exit_code,
    format_report,
    format_report_list,
    render_result_line,
    write_replays,
    write_report,
)
from repotrace.search import ReportFilter, filter_reports, report_exit_code
from repotrace.storage import BugReport, ReportStore

# Typer requires its Argument/Option factories in the signature, which B008 flags.
# ruff: noqa: B008

app = typer.Typer(
    name="repotrace",
    help="Turn failing commands into reproducible bug reports and regression tests.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()

DEFAULT_STORE = ".repotrace/reports"


def _store(root: str | None) -> ReportStore:
    return ReportStore(root or DEFAULT_STORE)


def _load(store: ReportStore, report_id: str) -> BugReport:
    try:
        return store.load(report_id)
    except FileNotFoundError as error:
        console.print(f"[red]no such report:[/red] {report_id}")
        raise typer.Exit(2) from error


def _replay_or_exit(
    report_id: str,
    store: ReportStore,
    *,
    cwd: str | None = None,
    timeout: float | None = None,
    match_output: bool = True,
) -> ReplayResult:
    """Replay ``report_id``, exiting with code 2 when the report is missing.

    ``replay_from_store`` re-reads the report from disk, so a report that
    vanished between listing and replaying must not escape as a traceback.
    """
    try:
        return replay_from_store(
            report_id, store, cwd=cwd, timeout=timeout, match_output=match_output
        )
    except FileNotFoundError as error:
        console.print(f"[red]no such report:[/red] {report_id}")
        raise typer.Exit(2) from error


def _write_or_exit(path: str, writer) -> None:
    try:
        written = writer()
    except OSError as error:
        console.print(f"[red]cannot write {path}:[/red] {error}")
        raise typer.Exit(2) from error
    console.print(f"wrote [cyan]{written}[/cyan]")


def _exit_code_for_result(outcome: Outcome) -> int:
    return 0 if outcome is Outcome.MATCHED else 1


def _print_plain(text: str) -> None:
    console.print(text, markup=False, highlight=False)


def _summary_from_results(results: Sequence[ReplayResult]) -> ReplaySummary:
    matched = sum(1 for result in results if result.matched)
    return build_summary(
        total=len(results),
        matched=matched,
        differed=len(results) - matched,
        results=list(results),
    )


def _print_replay_table(summary: ReplaySummary) -> None:
    table = Table(title="Replay summary")
    table.add_column("Report", style="cyan", no_wrap=True)
    table.add_column("Outcome")
    table.add_column("Exit code", justify="right")
    table.add_column("Differences")

    for result in summary.results:
        outcome = (
            "[green]reproduced[/green]" if result.matched else "[red]differs[/red]"
        )
        table.add_row(
            result.report_id or "(no id)",
            outcome,
            format_exit_code(result.exit_code),
            ", ".join(result.differences) or "none",
        )
    console.print(table)
    console.print(
        f"replayed [bold]{summary.total}[/bold] · "
        f"[green]reproduced {summary.matched}[/green] · "
        f"[red]differs {summary.differed}[/red] · "
        f"failed {summary.failed} · "
        f"reproducibility {summary.reproducible:.0%}"
    )


def _parse_filter_datetime(
    value: str, option: str, *, end_of_day: bool = False
) -> datetime:

    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise typer.BadParameter(
            f"invalid date {value!r}; use YYYY-MM-DD or ISO-8601",
            param_hint=option,
        ) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if end_of_day and len(text) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed.astimezone(UTC)


def _parse_filter_text(value: str | None, option: str) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        raise typer.BadParameter("value cannot be empty", param_hint=option)
    return text


def _parse_filter_tags(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    tags = tuple(dict.fromkeys(tag.strip() for tag in value.split(",") if tag.strip()))
    if not tags:
        raise typer.BadParameter(
            "provide at least one tag, e.g. --tags flaky,ci", param_hint="--tags"
        )
    return tags


def _print_search_results(reports: Sequence[BugReport]) -> None:
    table = Table(title="Search results")
    table.add_column("Report", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Severity")
    table.add_column("Exit code", justify="right")
    table.add_column("Tags")
    table.add_column("Created")

    for report in reports:
        table.add_row(
            report.id,
            report.title,
            report.severity or "—",
            format_exit_code(report_exit_code(report)),
            ", ".join(report.tags) or "—",
            format_datetime(report.created_at),
        )
    console.print(table)
    console.print(f"[dim]{len(reports)} matching report(s)[/dim]")


@app.command(
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        "allow_interspersed_args": False,
    }
)
def capture(
    command: list[str] = typer.Argument(..., help="Command to run and capture."),
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
    cwd: str | None = typer.Option(
        None, "--cwd", help="Working directory for the run."
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Seconds to wait before the command is killed."
    ),
    title: str | None = typer.Option(None, "--title", help="Title for the report."),
    report_id: str | None = typer.Option(
        None, "--id", help="Report id (default: a fresh UUID4)."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace an existing report with the same id."
    ),
    severity: str | None = typer.Option(
        None, "--severity", help="Severity, e.g. high."
    ),
    tags: str | None = typer.Option(
        None, "--tags", help="Comma separated tags, e.g. 'flaky,ci'."
    ),
    keep_going: bool = typer.Option(
        False,
        "--keep-going",
        help="Exit 0 even when the captured command failed.",
    ),
) -> None:
    """Run a command, record its trace, and persist a bug report."""
    tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()] if tags else None
    overrides: dict[str, object] = {}
    if tag_list is not None:
        overrides["tags"] = tag_list

    try:
        report_store = _store(store)
        if report_id is not None and not overwrite and report_store.exists(report_id):
            raise FileExistsError(f"Report {report_id!r} already exists.")
        trace, report = capture_command(
            command,
            store=report_store,
            cwd=cwd,
            timeout=timeout,
            title=title,
            report_id=report_id,
            severity=severity,
            overwrite=overwrite,
            **overrides,
        )
    except FileExistsError as error:
        console.print(f"[red]cannot save report:[/red] {error}")
        console.print("Use --overwrite to replace an existing report.")
        raise typer.Exit(2) from error
    except FileNotFoundError as error:
        console.print(f"[red]command not found:[/red] {error}")
        raise typer.Exit(2) from error

    console.print(f"captured [cyan]{report.id}[/cyan]")
    console.print(f"exit code [bold]{trace.exit_code}[/bold]")
    for event in trace.of_kind("stdout"):
        console.print(event.message, end="")
    for event in trace.of_kind("stderr"):
        console.print(f"[red]{event.message}[/red]", end="")

    if keep_going or trace.exit_code == 0:
        return
    raise typer.Exit(trace.exit_code if trace.exit_code else 1)


@app.command("list")
def list_reports(
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
) -> None:
    """List the identifiers of every stored report."""
    ids = _store(store).list_ids()
    if not ids:
        console.print("[dim]no reports stored[/dim]")
        return
    for report_id in ids:
        console.print(report_id)
    console.print(f"\n[dim]{len(ids)} report(s)[/dim]")


@app.command()
def search(
    title: str | None = typer.Option(
        None,
        "--title",
        help="Case-insensitive substring of the report title.",
    ),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help="Comma-separated tags; every tag must be present, e.g. 'flaky,ci'.",
    ),
    severity: str | None = typer.Option(
        None, "--severity", help="Severity to match, e.g. high."
    ),
    exit_code: int | None = typer.Option(
        None, "--exit-code", help="Exit code recorded in the report metadata."
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Include reports created on or after this date (YYYY-MM-DD or ISO-8601).",
    ),
    until: str | None = typer.Option(
        None,
        "--until",
        help="Include reports created on or before this date (YYYY-MM-DD or ISO-8601).",
    ),
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
    as_markdown: bool = typer.Option(
        False, "--markdown", help="Render results as a Markdown table."
    ),
) -> None:
    """Search stored reports by title, tags, severity, exit code, or date."""
    start = _parse_filter_datetime(since, "--since") if since is not None else None
    end = (
        _parse_filter_datetime(until, "--until", end_of_day=True)
        if until is not None
        else None
    )
    if start is not None and end is not None and start > end:
        raise typer.BadParameter(
            "--since must be on or before --until", param_hint="--since/--until"
        )

    criteria = ReportFilter(
        title=_parse_filter_text(title, "--title"),
        tags=_parse_filter_tags(tags),
        severity=_parse_filter_text(severity, "--severity"),
        exit_code=exit_code,
        since=start,
        until=end,
    )

    reports = filter_reports(_store(store).list(), criteria)
    if not reports:
        console.print("[dim]no matching reports[/dim]")
        return

    if as_markdown:
        _print_plain(format_report_list(reports))
        return
    _print_search_results(reports)


@app.command()
def show(
    report_id: str = typer.Argument(..., help="Identifier of the report to inspect."),
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
    as_markdown: bool = typer.Option(
        False, "--markdown", help="Render the report as Markdown instead of a table."
    ),
) -> None:
    """Print a stored report's metadata."""
    report = _load(_store(store), report_id)
    if as_markdown:
        _print_plain(format_report(report))
        return

    table = Table(title=f"Report {report.id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for field in (
        "id",
        "title",
        "status",
        "severity",
        "reporter",
        "assignee",
        "tags",
        "created_at",
        "updated_at",
        "description",
    ):
        value = getattr(report, field, None)
        if isinstance(value, list):
            value = ", ".join(value)
        table.add_row(field, str(value) if value else "—")
    console.print(table)

    if report.metadata:
        console.print("\n[bold]metadata[/bold]")
        for key in sorted(report.metadata):
            console.print(f"  [cyan]{key}[/cyan]: {report.metadata[key]!r}")


@app.command()
def replay(
    report_id: str = typer.Argument(..., help="Identifier of the report to replay."),
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
    cwd: str | None = typer.Option(
        None, "--cwd", help="Working directory (default: the recorded one)."
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Seconds to wait before the command is killed."
    ),
    exit_code_only: bool = typer.Option(
        False,
        "--exit-code-only",
        help="Compare exit codes only, ignoring captured output.",
    ),
    keep_going: bool = typer.Option(
        False,
        "--keep-going",
        help="Exit 0 even when the replay no longer reproduces.",
    ),
) -> None:
    """Re-run a stored command and compare it with the recorded failure."""
    result = _replay_or_exit(
        report_id,
        _store(store),
        cwd=cwd,
        timeout=timeout,
        match_output=not exit_code_only,
    )
    console.print(render_result_line(result))
    for difference in result.differences:
        console.print(f"  [red]{difference}[/red]")
    if keep_going:
        return
    raise typer.Exit(_exit_code_for_result(result.outcome))


@app.command("replay-all")
def replay_all_command(
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
    cwd: str | None = typer.Option(
        None, "--cwd", help="Working directory (default: each recorded one)."
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Seconds to wait before each command is killed."
    ),
    exit_code_only: bool = typer.Option(
        False,
        "--exit-code-only",
        help="Compare exit codes only, ignoring captured output.",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the sweep as Markdown to this file instead of the console.",
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace the output file if it already exists."
    ),
    keep_going: bool = typer.Option(
        False,
        "--keep-going",
        help="Exit 0 even when some replays no longer reproduce.",
    ),
) -> None:
    """Replay every stored report and summarise the outcomes."""
    summary = replay_all(
        _store(store),
        cwd=cwd,
        timeout=timeout,
        match_output=not exit_code_only,
    )
    if output:
        _write_or_exit(
            output, lambda: write_replays(summary, output, overwrite=overwrite)
        )
    else:
        _print_replay_table(summary)

    if summary.differed == 0 or keep_going:
        return
    raise typer.Exit(1)


@app.command()
def report(
    report_id: str = typer.Argument(..., help="Identifier of the report to render."),
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the Markdown report to this file instead of the console.",
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace the output file if it already exists."
    ),
    with_replay: bool = typer.Option(
        False,
        "--replay",
        help="Replay the report first and include the verdict in the report.",
    ),
    no_metadata: bool = typer.Option(
        False, "--no-metadata", help="Omit the metadata section."
    ),
    no_events: bool = typer.Option(
        False, "--no-events", help="Omit the event listing."
    ),
) -> None:
    """Render a stored report as Markdown, optionally with its replay verdict."""
    store_obj = _store(store)
    report_obj = _load(store_obj, report_id)
    include_metadata = not no_metadata
    include_events = not no_events

    result = None
    if with_replay:
        result = _replay_or_exit(report_id, store_obj)
        console.print(render_result_line(result))

    if output:
        _write_or_exit(
            output,
            lambda: write_report(
                report_obj,
                output,
                result=result,
                include_metadata=include_metadata,
                include_events=include_events,
                overwrite=overwrite,
            ),
        )
    else:
        _print_plain(
            format_report(
                report_obj,
                result=result,
                include_metadata=include_metadata,
                include_events=include_events,
            )
        )


@app.command()
def generate(
    report_id: str = typer.Argument(
        ..., help="Identifier of the report to generate a test from."
    ),
    store: str | None = typer.Option(
        None,
        "--store",
        "-s",
        help=f"Report store directory (default: {DEFAULT_STORE}).",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination test file (default: printed to the console).",
    ),
    function_name: str | None = typer.Option(
        None,
        "--name",
        help="Test function name (default: derived from the report id).",
    ),
    exit_code_only: bool = typer.Option(
        False,
        "--exit-code-only",
        help="Assert the exit code only, not captured output.",
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace the output file if it already exists."
    ),
) -> None:
    """Generate a standalone pytest regression test from a stored report."""
    report_obj = _load(_store(store), report_id)
    match_output = not exit_code_only

    if output:
        _write_or_exit(
            output,
            lambda: write_test(
                report_obj,
                output,
                function_name=function_name,
                match_output=match_output,
                overwrite=overwrite,
            ),
        )
        return

    _print_plain(
        generate_test(
            report_obj,
            function_name=function_name,
            match_output=match_output,
        )
    )


@app.command()
def version() -> None:
    """Print the installed RepoTrace version."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _version

    try:
        console.print(_version("repotrace"))
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        console.print("[dim]unknown[/dim]")


__all__ = [
    "app",
    "capture",
    "generate",
    "list_reports",
    "main",
    "replay",
    "replay_all_command",
    "report",
    "search",
    "show",
    "version",
]


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
