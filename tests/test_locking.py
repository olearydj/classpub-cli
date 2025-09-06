from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import os

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_single_writer_lock_busy(cli_runner: CliRunner, tmp_repo, monkeypatch):
    # Simulate an active lock owned by a live PID (this PID) and fresh timestamp
    Path(".classpub.lock").write_text(
        f"pid: {os.getpid()}\n" f"host: test\n" f"time: {datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    res = cli_runner.invoke(app, ["sync", "--yes"])  # any sync
    assert res.exit_code == 75
    assert "Another sync is already running" in res.stdout


def test_stale_lock_cleared(cli_runner: CliRunner, tmp_repo):
    # Write stale lock (dead pid and old timestamp)
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    Path(".classpub.lock").write_text(
        f"pid: 0\n" f"host: test\n" f"time: {stale_time}\n",
        encoding="utf-8",
    )
    # Minimal manifest/file to allow a normal sync
    (Path("pending") / "RELEASES.txt").write_text("", encoding="utf-8")
    res = cli_runner.invoke(app, ["sync", "--yes"])
    assert res.exit_code == 0
    # Lock should be removed by completion
    assert Path(".classpub.lock").exists() is False


def test_corrupt_lock_file_allows_progress(cli_runner: CliRunner, tmp_repo):
    # Write corrupt/garbage lock content
    Path(".classpub.lock").write_text("corrupt$$$\n\n???", encoding="utf-8")
    (Path("pending") / "RELEASES.txt").write_text("", encoding="utf-8")
    res = cli_runner.invoke(app, ["sync", "--yes"])
    assert res.exit_code == 0
    assert Path(".classpub.lock").exists() is False


def test_lock_ttl_boundary(cli_runner: CliRunner, tmp_repo):
    from datetime import timedelta
    # Below TTL → busy
    fresh = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    Path(".classpub.lock").write_text(
        f"pid: 0\n" f"host: test\n" f"time: {fresh}\n",
        encoding="utf-8",
    )
    res1 = cli_runner.invoke(app, ["sync", "--yes"])
    assert res1.exit_code == 75
    # Above TTL → proceed
    stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    Path(".classpub.lock").write_text(
        f"pid: 0\n" f"host: test\n" f"time: {stale}\n",
        encoding="utf-8",
    )
    (Path("pending") / "RELEASES.txt").write_text("", encoding="utf-8")
    res2 = cli_runner.invoke(app, ["sync", "--yes"])
    assert res2.exit_code == 0


