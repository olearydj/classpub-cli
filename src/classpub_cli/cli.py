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


def main() -> None:
    app()


if __name__ == "__main__":
    main()


