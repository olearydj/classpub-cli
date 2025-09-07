from __future__ import annotations

from typer.testing import CliRunner
import re

from classpub_cli.cli import app


def test_help_shows_usage_and_commands():
    runner = CliRunner()
    # Disable color to make help deterministic in non-TTY test envs
    res = runner.invoke(
        app,
        ["--help"],
        env={
            "CLICOLOR": "0",
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
            "TERM": "dumb",
        },
    )
    assert res.exit_code == 0
    out = res.stdout
    # Strip ANSI escape sequences if any remain
    out = re.sub(r"\x1b\[[0-9;]*[mK]", "", out)
    assert "Usage: classpub" in out or "Usage: " in out
    # Global options
    assert "--version" in out
    assert "--log-format" in out
    # Commands
    assert "init" in out
    assert "validate" in out


