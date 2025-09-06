from __future__ import annotations

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_help_shows_usage_and_commands():
    runner = CliRunner()
    res = runner.invoke(app, ["--help"])  # prints help
    assert res.exit_code == 0
    out = res.stdout
    assert "Usage: classpub" in out or "Usage: " in out
    # Global options
    assert "--version" in out
    assert "--log-format" in out
    # Commands
    assert "init" in out
    assert "validate" in out


