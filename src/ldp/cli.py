"""CLI entry point: ldp poll | draft | run | status | drafts."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .drafter import Drafter
from .github_poller import GitHubPoller
from .models import Draft, Event
from .store import Store

app = typer.Typer(help="linkedin-dev-pipeline: GitHub activity → LinkedIn drafts.")
console = Console()


def _project_root() -> Path:
    return Path.cwd()


def _draft_path(cfg) -> Path:
    p = _project_root() / cfg.drafts_dir
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_draft_file(cfg, draft: Draft) -> Path:
    drafts_dir = _draft_path(cfg)
    stamp = draft.created_at.strftime("%Y%m%d-%H%M%S")
    fname = f"{stamp}-{draft.category}-{draft.id[:8]}.md"
    path = drafts_dir / fname
    header = (
        f"---\n"
        f"id: {draft.id}\n"
        f"category: {draft.category}\n"
        f"status: {draft.status}\n"
        f"created_at: {draft.created_at.isoformat()}\n"
        f"event_ids: {', '.join(draft.event_ids)}\n"
        f"---\n\n"
    )
    path.write_text(header + draft.body + "\n")
    return path


@app.command()
def poll(
    dry: bool = typer.Option(False, "--dry", help="List what would be stored without saving."),
):
    """Poll GitHub for new activity and store new events."""
    cfg = load_config()
    if not cfg.github_token:
        console.print("[red]GITHUB_TOKEN not set.[/red]")
        raise typer.Exit(1)
    poller = GitHubPoller(cfg)
    store = None if dry else Store(_project_root() / cfg.state_db)
    new_count = 0
    seen_count = 0
    table = Table(title="Polled events")
    table.add_column("kind", style="cyan")
    table.add_column("source", style="magenta")
    table.add_column("repo#n")
    table.add_column("title")
    for ev in poller.poll_all():
        if dry:
            table.add_row(ev.kind, ev.source, f"{ev.repo}#{ev.number}", ev.title[:60])
            seen_count += 1
            continue
        is_new = store.upsert_event(ev)
        if is_new:
            new_count += 1
            table.add_row(ev.kind, ev.source, f"{ev.repo}#{ev.number}", ev.title[:60])
    console.print(table)
    if dry:
        console.print(f"[yellow]Dry run: {seen_count} events seen, nothing stored.[/yellow]")
    else:
        store.close()
        console.print(f"[green]Stored {new_count} new event(s).[/green]")


@app.command()
def draft(
    category: str | None = typer.Option(None, "--category", "-c", help="Force a content category."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max events to consider."),
):
    """Draft a LinkedIn post from recent stored events."""
    cfg = load_config()
    if not cfg.openrouter_api_key:
        console.print("[red]OPENROUTER_API_KEY not set.[/red]")
        raise typer.Exit(1)
    store = Store(_project_root() / cfg.state_db)
    events = store.draftable_events(limit=limit)
    if not events:
        console.print("[yellow]No substantive events in store. Run `ldp poll` first.[/yellow]")
        store.close()
        raise typer.Exit(0)

    # group: prefer a coherent batch of the same kind for a single post
    batch = _select_batch(events)
    console.print(
        f"[cyan]Drafting from {len(batch)} event(s), category={category or 'auto'}[/cyan]"
    )
    for e in batch:
        console.print(f"  [dim]- {e.summary()}[/dim]")

    with Drafter(cfg) as d:
        result = d.draft(batch, category=category)
    if not result:
        console.print(
            "[yellow]Drafter returned NOT_ENOUGH_CONTEXT. Try more events or a different category.[/yellow]"
        )
        store.close()
        raise typer.Exit(0)

    store.save_draft(result)
    path = _write_draft_file(cfg, result)
    store.close()
    console.print(f"[green]Draft written:[/green] {path}")
    console.print("\n--- draft preview ---\n")
    console.print(result.body)
    console.print("\n--- end ---")


def _select_batch(events: list[Event]) -> list[Event]:
    """Pick a coherent subset for one post.

    Prefers events that actually have title/body content (GitHub's user event
    API returns sparse payloads for PR open/review/close events, but rich
    content for issue comments). Groups by repo+number when possible so the
    drafter gets full context on one piece of work.
    """
    if not events:
        return []
    # only events with real content
    substantive = [e for e in events if e.title or e.body]
    if not substantive:
        return events[:3]

    # group by repo+number to give the drafter full context on one PR/issue
    groups: dict[str, list[Event]] = {}
    for e in substantive:
        key = f"{e.repo}#{e.number}" if e.number else e.repo
        groups.setdefault(key, []).append(e)

    # prefer groups with the most events (richest context), then by kind priority
    priority = {"issue_commented": 0, "pr_merged": 1, "issue_opened": 2, "pr_opened": 3, "opportunity": 4}

    def group_score(item: tuple[str, list[Event]]) -> tuple:
        _key, evs = item
        best_kind = min((priority.get(e.kind, 99) for e in evs), default=99)
        return (-len(evs), best_kind)

    best_key = min(groups.items(), key=group_score)[0]
    return groups[best_key][:5]


@app.command()
def run(
    category: str | None = typer.Option(None, "--category", "-c"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """Poll then draft in one step."""
    poll(dry=False)
    draft(category=category, limit=limit)


@app.command()
def status():
    """Show store summary."""
    cfg = load_config()
    store = Store(_project_root() / cfg.state_db)
    events = store.recent_events(limit=200)
    drafts = store.list_drafts(limit=200)
    table = Table(title="Events by kind")
    table.add_column("kind")
    table.add_column("count", justify="right")
    counts: dict[str, int] = {}
    for e in events:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        table.add_row(k, str(v))
    console.print(table)
    console.print(f"[cyan]Total recent events: {len(events)}[/cyan]")
    console.print(f"[cyan]Total drafts: {len(drafts)}[/cyan]")
    store.close()


@app.command(name="drafts")
def list_drafts(
    status_filter: str | None = typer.Option(None, "--status", "-s"),
):
    """List stored drafts."""
    cfg = load_config()
    store = Store(_project_root() / cfg.state_db)
    drafts = store.list_drafts(status=status_filter)
    table = Table(title="Drafts")
    table.add_column("id", style="dim")
    table.add_column("category")
    table.add_column("status")
    table.add_column("created")
    table.add_column("preview")
    for d in drafts:
        table.add_row(
            d.id[:8],
            d.category,
            d.status,
            d.created_at.strftime("%Y-%m-%d %H:%M"),
            d.body[:60].replace("\n", " "),
        )
    console.print(table)
    store.close()


@app.command()
def approve(
    draft_id: str = typer.Argument(..., help="Draft id (or unique prefix)."),
):
    """Mark a draft as approved (ready to publish manually)."""
    cfg = load_config()
    store = Store(_project_root() / cfg.state_db)
    drafts = store.list_drafts()
    match = next((d for d in drafts if d.id.startswith(draft_id)), None)
    if not match:
        console.print("[red]No matching draft.[/red]")
        store.close()
        raise typer.Exit(1)
    store.update_draft_status(match.id, "approved")
    console.print(f"[green]Approved {match.id[:8]} ({match.category})[/green]")
    store.close()


if __name__ == "__main__":
    app()
