from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_init_creates_manifest(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["init"])  # classpub init
        assert result.exit_code == 0
        assert (Path("pending") / "RELEASES.txt").exists()
        assert "Created pending/RELEASES.txt" in result.stdout


def test_init_idempotent(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (Path("pending")).mkdir(exist_ok=True)
        (Path("pending") / "RELEASES.txt").write_text("# Released Files\n\n")
        result = runner.invoke(app, ["init"])  # classpub init
        assert result.exit_code == 0
        assert "already exists" in result.stdout


