from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_clean_removes_counts(cli_runner: CliRunner, tmp_repo):
    # Arrange ds_store files and checkpoints dirs under pending and preview
    (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "notebooks" / ".DS_Store").write_text("x\n", encoding="utf-8")
    (Path("preview") / "images").mkdir(parents=True, exist_ok=True)
    (Path("preview") / "images" / ".DS_Store").write_text("x\n", encoding="utf-8")
    (Path("pending") / "a" / ".ipynb_checkpoints").mkdir(parents=True, exist_ok=True)
    (Path("preview") / "b" / ".ipynb_checkpoints").mkdir(parents=True, exist_ok=True)

    res = cli_runner.invoke(app, ["clean"])  # acquire lock and remove
    assert res.exit_code == 0
    out = res.stdout
    # Should report at least 2 files or dirs depending on platform
    assert "✓ Clean complete: " in out
    # Confirm removals actually happened
    assert (Path("pending") / "notebooks" / ".DS_Store").exists() is False
    assert (Path("preview") / "images" / ".DS_Store").exists() is False
    assert (Path("pending") / "a" / ".ipynb_checkpoints").exists() is False
    assert (Path("preview") / "b" / ".ipynb_checkpoints").exists() is False


def test_clean_lock_contention_returns_75(cli_runner: CliRunner, tmp_repo):
    # Create a live lock that appears fresh
    Path(".classpub.lock").write_text("pid: 999999\nhost: test\ntime: 2099-01-01T00:00:00+00:00\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["clean"])  # should detect busy
    assert res.exit_code == 75
    assert "Another operation is already running" in res.stdout


