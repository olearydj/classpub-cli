from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from .logging import get_console, setup_logging
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


app = typer.Typer(add_completion=False, help="Classpub CLI")


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


@app.callback(context_settings={"help_option_names": ["-h", "--help"]})
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
    ctx.obj = {"no_color": no_color}


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


@app.command()
def validate(ctx: typer.Context) -> typer.Exit:
    """Phase 0: Check required Python deps and Git CLI version."""
    no_color = ctx.obj.get("no_color", False)
    console = get_console(no_color=no_color)
    missing = utils.check_python_deps()
    if missing:
        for name in missing:
            console.print(f"❌ Missing dependency: {name}", highlight=False)
        raise typer.Exit(code=1)

    ok, ver = utils.git_version_ok()
    if not ok:
        console.print("❌ Git >= 2.20 required for diff", highlight=False)
        raise typer.Exit(code=1)

    console.print("✅ Dependencies OK", highlight=False)
    console.print(f"✅ Git OK", highlight=False)
    raise typer.Exit(code=0)


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


@app.command(name="add")
def add_alias(ctx: typer.Context, item: str = typer.Argument(..., help="Alias for release")) -> typer.Exit:
    return release_cmd(ctx, item)


@app.command(name="remove")
def remove_cmd(ctx: typer.Context, item: str = typer.Argument(..., help="File or folder to remove from release manifest")) -> typer.Exit:
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()


