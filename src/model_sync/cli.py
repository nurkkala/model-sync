"""The `model-sync` command: `status`, `diff`, and `apply`."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape

from model_sync.consumers import CONSUMERS
from model_sync.index import ConfigError, Index, config_path, load_index, state_dir
from model_sync.plan import ABSENT, ConsumerPlan, Stale, plan_consumer
from model_sync.probes import PROBES, ProbeResult, run_probe
from model_sync.resolve import resolve
from model_sync.version import report

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Probe model providers and write what they serve into each consumer's configuration.",
)
out = Console(highlight=False, soft_wrap=True)
err = Console(stderr=True, highlight=False)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="The provider index to read instead of the default."),
]
ConsumerArgument = Annotated[
    list[str] | None,
    typer.Argument(
        help="Consumers to act on; every consumer in the index when omitted."
    ),
]


def _version(show: bool) -> None:
    if show:
        for line in report():
            typer.echo(line)
        raise typer.Exit()


@app.callback()
def main(
    _: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version,
            is_eager=True,
            help="Print the version and the code behind it, and exit.",
        ),
    ] = False,
) -> None:
    pass


def _fail(message: str) -> typer.Exit:
    err.print(f"[red]error:[/red] {escape(message)}")
    return typer.Exit(2)


def _load(config: Path | None) -> Index:
    try:
        index = load_index(config or config_path())
    except ConfigError as error:
        raise _fail(str(error)) from None
    for provider_id, provider in index.providers.items():
        if provider.kind not in PROBES:
            raise _fail(
                f"providers.{provider_id}.kind: no probe named {provider.kind!r}; "
                f"known kinds are {', '.join(sorted(PROBES))}"
            )
    for name, consumer in index.consumers.items():
        if consumer.kind not in CONSUMERS:
            raise _fail(
                f"consumers.{name}.kind: no consumer named {consumer.kind!r}; "
                f"known kinds are {', '.join(sorted(CONSUMERS))}"
            )
    return index


def _probe_all(index: Index, only: set[str] | None = None) -> dict[str, ProbeResult]:
    results = {}
    for provider_id, provider in index.providers.items():
        if only is None or provider_id in only:
            with err.status(f"asking {provider_id}"):
                results[provider_id] = run_probe(provider)
    return results


def _plans(index: Index, names: list[str] | None) -> list[ConsumerPlan]:
    for name in names or []:
        if name not in index.consumers:
            raise _fail(
                f"no consumer named {name!r}; the index has {', '.join(index.consumers) or 'none'}"
            )
    chosen = names or list(index.consumers)
    if not chosen:
        raise _fail("the index lists no consumers")
    needed = set()
    for name in chosen:
        listed = index.consumers[name].providers
        needed |= set(
            listed
            if listed is not None
            else [provider_id for provider_id, p in index.providers.items() if p.sync]
        )
    probes = _probe_all(index, needed)
    return [plan_consumer(name, index, probes) for name in chosen]


def _show(value: Any) -> str:
    return "(absent)" if value is ABSENT else json.dumps(value, ensure_ascii=False)


def _print_plan(plan: ConsumerPlan) -> None:
    out.print(f"[bold]{escape(plan.name)}[/bold]  {escape(str(plan.path))}")
    if plan.error:
        out.print(f"  [red]skipped:[/red] {escape(plan.error)}")
        return
    for step in plan.providers:
        if not step.reachable:
            out.print(
                f"  [bold]{escape(step.provider_id)}[/bold]  [yellow]unreachable[/yellow] "
                f"({escape(step.reason or 'no reason given')}); "
                f"{step.kept} {'entry' if step.kept == 1 else 'entries'} left as they are"
            )
            continue
        state = "" if step.has_changes else "  [dim]up to date[/dim]"
        new_block = "  [green]new provider block[/green]" if step.created else ""
        out.print(
            f"  [bold]{escape(step.provider_id)}[/bold]  {step.live} live{new_block}{state}"
        )
        for model_id in step.added:
            out.print(f"    [green]+ {escape(model_id)}[/green]")
        for model_id in step.removed:
            out.print(f"    [red]- {escape(model_id)}[/red]")
        for model_id, changes in step.changed.items():
            out.print(f"    [yellow]~ {escape(model_id)}[/yellow]")
            for key, old, new in changes:
                out.print(
                    f"        {escape(key)}: {escape(_show(old))} -> {escape(_show(new))}"
                )
    for warning in plan.warnings:
        out.print(f"  [yellow]warning:[/yellow] {escape(warning)}")


@app.command()
def status(config: ConfigOption = None) -> None:
    """Ask every provider in the index what it serves, and show the answer."""
    index = _load(config)
    probes = _probe_all(index)
    for provider_id, provider in index.providers.items():
        result = probes[provider_id]
        title = f"[bold]{escape(provider_id)}[/bold]  {escape(provider.kind)}  {escape(provider.base_url)}"
        if not provider.sync:
            title += "  [dim]status only[/dim]"
        if not result.reachable:
            out.print(
                f"{title}  [yellow]unreachable[/yellow] ({escape(result.error or '')})"
            )
            continue
        out.print(f"{title}  {len(result.models)} live")
        rows = [("model", "name", "context", "output", "sees", "tools", "reasons")]
        rows += [
            (
                model.id,
                model.name,
                "?" if model.context is None else str(model.context),
                "?" if model.max_output is None else str(model.max_output),
                "text, image" if model.vision else "text",
                "yes" if model.tools else "no",
                "yes" if model.reasoning else "no",
            )
            for model in resolve(provider, result.models)
        ]
        # Padded by hand: a rich table truncates a model id to fit a narrow terminal, and
        # the id is the one column that must be readable whole.
        widths = [
            max(len(row[column]) for row in rows) for column in range(len(rows[0]))
        ]
        for number, row in enumerate(rows if result.models else []):
            cells = [
                cell.rjust(width) if column in (2, 3) else cell.ljust(width)
                for column, (cell, width) in enumerate(zip(row, widths))
            ]
            line = escape("  " + "  ".join(cells).rstrip())
            out.print(f"[dim]{line}[/dim]" if number == 0 else line)


@app.command()
def diff(
    consumers: ConsumerArgument = None,
    config: ConfigOption = None,
    exit_code: Annotated[
        bool, typer.Option("--exit-code", help="Exit 1 when any consumer would change.")
    ] = False,
) -> None:
    """Show what `apply` would change in each consumer's file, writing nothing."""
    plans = _plans(_load(config), consumers)
    for plan in plans:
        _print_plan(plan)
    if any(plan.error for plan in plans):
        raise typer.Exit(2)
    if exit_code and any(plan.has_changes for plan in plans):
        raise typer.Exit(1)


def _interactive() -> bool:
    """Whether someone is there to answer: `apply` asks nothing of a pipe or a script."""
    return sys.stdin.isatty()


def _ask(plan: ConsumerPlan, stale: Stale) -> None:
    """Ask what to do with one stale setting, and stage the answer."""
    reference = stale.reference
    out.print(
        f"  [bold]{escape(reference.where)}[/bold] names "
        f"{escape(reference.provider_id)}/{escape(reference.model_id)}. Replace it with:"
    )
    for number, (provider_id, model_id) in enumerate(plan.live, start=1):
        out.print(f"    {number:>2}  {escape(provider_id)}/{escape(model_id)}")
    out.print("     r  remove the setting")
    out.print("     l  leave it as it is")
    while True:
        answer = typer.prompt("  choice", default="l").strip().lower()
        if answer == "l":
            return
        if answer == "r":
            plan.consumer.drop(reference)
            out.print(f"  [red]removed[/red] {escape(reference.where)}")
            return
        if answer.isdigit() and 1 <= int(answer) <= len(plan.live):
            provider_id, model_id = plan.live[int(answer) - 1]
            plan.consumer.repoint(reference, provider_id, model_id)
            out.print(
                f"  [green]repointed[/green] {escape(reference.where)} "
                f"to {escape(provider_id)}/{escape(model_id)}"
            )
            return
        out.print(f"  [yellow]no such choice:[/yellow] {escape(answer)}")


@app.command()
def apply(consumers: ConsumerArgument = None, config: ConfigOption = None) -> None:
    """Write the live model lists into each consumer's file, keeping a backup of each.

    On a terminal, also ask what to do with each setting that names a model no longer
    served, unless the index has a table for that model.
    """
    plans = _plans(_load(config), consumers)
    backups = state_dir() / "backups"
    asking = _interactive()
    for plan in plans:
        _print_plan(plan)
        if plan.error:
            continue
        if asking:
            for stale in plan.stale:
                if not stale.expected:
                    _ask(plan, stale)
        for path, text in plan.consumer.pending(plan.has_changes):
            backup = plan.consumer.write(path, text, backups)
            kept = f"; the previous file is {backup}" if backup else ""
            out.print(f"  [green]wrote[/green] {escape(str(path))}{escape(kept)}")
    if any(plan.error for plan in plans):
        raise typer.Exit(2)
