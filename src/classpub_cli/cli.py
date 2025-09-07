from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from .logging import get_console, setup_logging
from .config import ensure_config_loaded, get_active_config
from . import __version__
from .paths import MANIFEST, PENDING
from . import utils
from .utils import (
    ensure_repo_root_present,
    resolve_item,
    Resolution,
    format_grouped_listing_for_not_found,
    format_ambiguity_list,
    read_manifest,
    format_entry_line,
    append_entry,
    remove_entry_by_raw,
)
from .paths import PREVIEW
from .status import compute_status, ItemStatus
from .validate import run_validate
from .clean import run_clean
from .sync import run_sync
from .diff import run_diff_all, run_diff_item
from .convert import run_to_md


app = typer.Typer(
    add_completion=False,
    help=(
        "Classpub CLI.\n\n"
        "Global options: --version, --log-format, -v/--verbose, -q/--quiet, --no-color."
    ),
)
config_app = typer.Typer(add_completion=False, help="Configuration commands")
app.add_typer(config_app, name="config")


def _write_manifest_header(path: Path) -> None:
    header = (
        "# Released Files (manifest)\n"
        "# Add files (e.g., notebooks/01.ipynb) or folders with trailing / (e.g., data/)\n"
        "# Lines starting with # are comments. Empty lines are ignored.\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(header, encoding="utf-8")


 
def _version_callback(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit(code=0)


@app.callback(context_settings={"help_option_names": ["-h", "--help"]}, invoke_without_command=True)
def cli_callback(
    ctx: typer.Context,
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Increase log verbosity"),
    quiet: int = typer.Option(0, "--quiet", "-q", count=True, help="Decrease log verbosity"),
    log_format: str = typer.Option("human", "--log-format", help="Log format: human or json"),
    log_level: Optional[str] = typer.Option(None, "--log-level", help="Console log level override"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable color output"),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the CLASSPUB version and exit",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    console_level = utils.compute_console_level(verbose, quiet, log_level)
    setup_logging(console_level, log_format, no_color)
    # Load project-local config (non-fatal for commands that don't require repo root)
    try:
        cfg = ensure_config_loaded(Path.cwd())
    except ValueError as e:
        # Defer surfacing to subcommands that depend on config; minimal logging here
        logging.getLogger(__name__).error("%s", e)
        cfg = get_active_config()
    ctx.obj = {"no_color": no_color, "config": cfg}
    # If invoked without a subcommand, show help explicitly so global options are visible
    if ctx.invoked_subcommand is None and not ctx.resilient_parsing:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)


@app.command()
def init(ctx: typer.Context) -> typer.Exit:
    """Create pending/RELEASES.txt with header comments if missing (idempotent)."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)
    if MANIFEST.exists():
        console.print("⚠️  pending/RELEASES.txt already exists", highlight=False)
        raise typer.Exit(code=0)
    _write_manifest_header(MANIFEST)
    console.print("✓ Created pending/RELEASES.txt", highlight=False)
    raise typer.Exit(code=0)


@config_app.command(name="init")
def config_init(ctx: typer.Context) -> typer.Exit:
    """Generate a fully commented classpub.toml in the repository root."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)
    # Require repository root (pending/ must exist)
    if not utils.ensure_repo_root_present():
        console.print("❌ Run from the repository root (pending/ missing)", highlight=False)
        raise typer.Exit(code=1)

    path = Path("classpub.toml")
    if path.exists():
        console.print("⚠️  classpub.toml already exists", highlight=False)
        raise typer.Exit(code=0)

    template = (
        "# classpub.toml\n\n"
        "[general]\n"
        "# strict = false      # Treat warnings as errors (validate exits 1).\n"
        "# assume_yes = false  # Auto-confirm destructive prompts (e.g., sync removals).\n\n"
        "[sync]\n"
        "# dry_run = false            # Compute the plan without writing.\n"
        "# large_file_warn_mb = 100   # Warn when hashing files larger than this size (MB).\n\n"
        "[ignore]\n"
        "# patterns = [\n"
        "#   \".DS_Store\",\n"
        "#   \".gitignore\",\n"
        "#   \".gitattributes\",\n"
        "#   \".ipynb_checkpoints/\",\n"
        "#   \"RELEASES.txt\",\n"
        "# ]\n\n"
        "[hash]\n"
        "# chunk_size = 8192   # Streaming chunk size in bytes for hashing.\n\n"
        "[logging]\n"
        "# level = \"INFO\"      # One of: ERROR, WARNING, INFO, DEBUG\n"
        "# format = \"human\"    # One of: human, json\n"
        "# timestamps = true    # Include timestamps in logs (JSON always includes ISO8601)\n"
    )
    path.write_text(template, encoding="utf-8")
    console.print("✓ Created classpub.toml", highlight=False)
    raise typer.Exit(code=0)


@app.command()
def validate(ctx: typer.Context) -> typer.Exit:
    """Validate repository structure and environment."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)

    def _print(line: str) -> None:
        console.print(line, highlight=False)

    code = run_validate(_print)
    raise typer.Exit(code=code)


@app.command()
def check(ctx: typer.Context) -> typer.Exit:
    """Show repository status for tracked and untracked items."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)
    if not utils.ensure_repo_root_present():
        console.print("❌ This command must be run from the repository root (missing 'pending/').", highlight=False)
        raise typer.Exit(code=1)

    report = compute_status()

    icon = {
        ItemStatus.SYNCED: "✅",
        ItemStatus.MODIFIED: "🔄",
        ItemStatus.TOUCHED: "👆",
        ItemStatus.STAGED: "📋",
        ItemStatus.UNTRACKED: "📄",
        ItemStatus.REMOVED: "⚠️",
    }

    for line in report.lines:
        prefix = icon[line.status]
        path_display = line.rel_path if not line.is_folder else (line.rel_path if line.rel_path.endswith("/") else line.rel_path + "/")
        if line.note == "missing_from_pending":
            console.print(f"⚠️  {path_display} (missing from pending)", highlight=False)
        elif line.status is ItemStatus.MODIFIED:
            console.print(f"{prefix} {path_display} (modified)", highlight=False)
        elif line.status is ItemStatus.TOUCHED:
            console.print(f"{prefix} {path_display} (touched)", highlight=False)
        elif line.status is ItemStatus.STAGED:
            console.print(f"{prefix} {path_display} (staged)", highlight=False)
        elif line.status is ItemStatus.UNTRACKED:
            console.print(f"{prefix} {path_display} (untracked)", highlight=False)
        elif line.status is ItemStatus.REMOVED:
            console.print(f"⚠️  {path_display} (removed)", highlight=False)
        else:
            console.print(f"{prefix} {path_display}", highlight=False)

    c = report.counters
    console.print(
        f"Synced: {c.synced}, Modified: {c.modified}, Touched: {c.touched}, "
        f"Staged: {c.staged}, Untracked: {c.untracked}, Removed: {c.removed}",
        highlight=False,
    )

    raise typer.Exit(code=0)


@app.command()
def sync(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve removals"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change; do not write files"),
) -> typer.Exit:
    """Synchronize tracked items from pending/ to preview/ with optional removals."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)

    def _print(line: str) -> None:
        console.print(line, highlight=False)

    code = run_sync(assume_yes=yes, dry_run=dry_run, console_print=_print)
    raise typer.Exit(code=code)


@app.command(name="release")
def release_cmd(ctx: typer.Context, item: str = typer.Argument(..., help="File or folder to mark for release")) -> typer.Exit:
    """Mark a file or folder under pending/ for release (alias: add)."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)
    if not ensure_repo_root_present():
        console.print("❌ This command must be run from the repository root (missing 'pending/').", highlight=False)
        raise typer.Exit(code=1)

    res = resolve_item(item)
    if res.status == Resolution.ERROR:
        console.print(f"❌ {res.message}", highlight=False)
        raise typer.Exit(code=1)
    if res.status == Resolution.NOT_FOUND:
        console.print(f"❌ File or folder not found: {item}", highlight=False)
        for line in format_grouped_listing_for_not_found():
            console.print(line, highlight=False)
        raise typer.Exit(code=1)
    if res.status == Resolution.AMBIGUOUS and res.candidates:
        console.print(f"❌ Ambiguous item: {item}", highlight=False)
        for line in format_ambiguity_list(res.candidates):
            console.print(line, highlight=False)
        raise typer.Exit(code=1)

    assert res.rel is not None and res.is_dir is not None
    raw = format_entry_line(res.rel, res.is_dir)
    added, _ = append_entry(res.rel, res.is_dir)
    if added:
        console.print(f"✓ Marked {raw} for release", highlight=False)
        console.print("Run 'classpub sync' to copy to public folder", highlight=False)
    else:
        console.print(f"⚠️  {raw} is already released", highlight=False)
    raise typer.Exit(code=0)


@app.command(
    name="add",
    help="Alias for 'release': mark a file or folder under pending/ for release",
)
def add_alias(ctx: typer.Context, item: str = typer.Argument(..., help="Alias for release")) -> typer.Exit:
    """Alias for 'release': mark a file or folder under pending/ for release."""
    return release_cmd(ctx, item)


@app.command(
    name="remove",
    help="Remove a file or folder from the release manifest (pending/RELEASES.txt)",
)
def remove_cmd(ctx: typer.Context, item: str = typer.Argument(..., help="File or folder to remove from release manifest")) -> typer.Exit:
    """Remove a file or folder from the release manifest (pending/RELEASES.txt)."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)

    if not ensure_repo_root_present():
        console.print("❌ This command must be run from the repository root (missing 'pending/').", highlight=False)
        raise typer.Exit(code=1)

    if not MANIFEST.exists():
        console.print("❌ pending/RELEASES.txt is missing", highlight=False)
        raise typer.Exit(code=1)

    res = resolve_item(item)
    if res.status == Resolution.ERROR:
        console.print(f"❌ {res.message}", highlight=False)
        raise typer.Exit(code=1)
    if res.status == Resolution.NOT_FOUND:
        console.print(f"❌ File or folder not found: {item}", highlight=False)
        for line in format_grouped_listing_for_not_found():
            console.print(line, highlight=False)
        raise typer.Exit(code=1)
    if res.status == Resolution.AMBIGUOUS and res.candidates:
        console.print(f"❌ Ambiguous item: {item}", highlight=False)
        for line in format_ambiguity_list(res.candidates):
            console.print(line, highlight=False)
        raise typer.Exit(code=1)

    assert res.rel is not None and res.is_dir is not None
    raw = format_entry_line(res.rel, res.is_dir)
    entries = read_manifest()
    if any(e.raw == raw for e in entries):
        removed = remove_entry_by_raw(raw)
        if removed:
            console.print(f"✓ Removed {raw} from release manifest", highlight=False)
            # Optional hint per TDD §7.3
            # If corresponding item still exists in preview/, suggest sync
            dst = (PREVIEW / res.rel) if not res.is_dir else (PREVIEW / res.rel)
            if (dst.exists() if dst else False):
                console.print("ℹ️  Item still exists in preview/ - run 'classpub sync' to remove it", highlight=False)
        else:
            # Unexpected, but keep exit 0 per spec on not present
            console.print(f"⚠️  {raw} is not in release manifest", highlight=False)
            console.print("Currently released files:", highlight=False)
            for e in entries:
                console.print(f"  {e.raw}", highlight=False)
        raise typer.Exit(code=0)
    else:
        console.print(f"⚠️  {raw} is not in release manifest", highlight=False)
        console.print("Currently released files:", highlight=False)
        for e in entries:
            console.print(f"  {e.raw}", highlight=False)
        raise typer.Exit(code=0)


@app.command()
def diff(ctx: typer.Context, item: Optional[str] = typer.Argument(None)) -> typer.Exit:
    """Show diffs between preview/ and pending/ for tracked files and folders.

    Without arguments, iterates manifest entries; with ITEM, resolves like release/remove and diffs that item.
    """
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)

    def _print(line: str) -> None:
        console.print(line, highlight=False)

    if item is None:
        code = run_diff_all(_print)
        raise typer.Exit(code=code)
    else:
        code = run_diff_item(item, _print)
        raise typer.Exit(code=code)


@app.command(name="to-md")
def to_md(
    ctx: typer.Context,
    source: str = typer.Option("pending", "--source", help="Notebook source: pending or preview"),
    outputs: str = typer.Option("strip", "--outputs", help="Output policy: strip or keep"),
    execute: bool = typer.Option(False, "--execute", help="Execute notebooks in current venv before converting"),
) -> typer.Exit:
    """Convert notebooks to Markdown under pending/md/..."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)
    if not utils.ensure_repo_root_present():
        console.print("❌ This command must be run from the repository root (missing 'pending/').", highlight=False)
        raise typer.Exit(code=1)

    def _print(line: str) -> None:
        console.print(line, highlight=False)

    code = run_to_md(source=source, outputs=outputs, execute=execute, console_print=_print)
    raise typer.Exit(code=code)


@app.command()
def clean(ctx: typer.Context) -> typer.Exit:
    """Remove .DS_Store files and .ipynb_checkpoints directories under pending/ and preview/."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)

    def _print(line: str) -> None:
        console.print(line, highlight=False)

    code = run_clean(_print)
    raise typer.Exit(code=code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()


