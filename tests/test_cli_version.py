from __future__ import annotations

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_version_flag_prints_version():
    runner = CliRunner()
    res = runner.invoke(app, ["--version"])  # early exit
    assert res.exit_code == 0
    assert res.stdout.strip() != ""
    # Basic semantic: contains dots typical of semver or fallback
    assert "." in res.stdout.strip()


