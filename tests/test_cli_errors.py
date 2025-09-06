from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_check_requires_repo_root(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # no pending/
        res = runner.invoke(app, ["check"])
        assert res.exit_code == 1
        assert "repository root" in res.stdout


def test_remove_requires_repo_root(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        res = runner.invoke(app, ["remove", "anything"])
        assert res.exit_code == 1
        assert "repository root" in res.stdout


def test_remove_ambiguous_and_not_in_manifest_listing(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Set up repo with pending but an ambiguous basename for remove
        (Path("pending") / "dir1").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "dir1" / "target").write_text("x\n", encoding="utf-8")
        (Path("pending") / "dir2" / "target").mkdir(parents=True, exist_ok=True)
        # Ensure manifest exists so remove flows to resolution path
        (Path("pending") / "RELEASES.txt").write_text("", encoding="utf-8")
        # Ambiguous remove
        r1 = runner.invoke(app, ["remove", "target"])
        assert r1.exit_code == 1
        assert "Ambiguous" in r1.stdout

        # Deterministic not-in-manifest listing case
        # Manifest contains only images/
        (Path("pending") / "images").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "images" / "logo.png").write_text("b\n", encoding="utf-8")
        (Path("pending") / "docs").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "docs" / "readme.md").write_text("hi\n", encoding="utf-8")
        # add images/
        runner.invoke(app, ["release", "images/"])
        # remove docs/readme.md (resolves, but not in manifest)
        r2 = runner.invoke(app, ["remove", "docs/readme.md"])
        assert r2.exit_code == 0
        assert "is not in release manifest" in r2.stdout
        assert "Currently released files:" in r2.stdout
        assert "images/" in r2.stdout


