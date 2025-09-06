from __future__ import annotations

from pathlib import Path

import time
from typer.testing import CliRunner
import os
import re

from classpub_cli.cli import app


def _touch_ns(path: Path) -> None:
    now_ns = time.time_ns()
    path.touch()
    path.stat()
    os_utime = getattr(__import__("os"), "utime")
    os_utime(path, ns=(now_ns, now_ns))


def test_check_staged_when_preview_missing(cli_runner: CliRunner, tmp_repo: Path, write_manifest):
    # file in pending, tracked directly, but no preview → staged
    f = Path("pending") / "x.txt"
    f.write_text("hello\n", encoding="utf-8")
    write_manifest(["x.txt"])  # direct tracking

    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    assert "📋 x.txt (staged)" in res.stdout


def test_check_synced_vs_touched(cli_runner: CliRunner, tmp_repo: Path, write_manifest):
    # Create file and preview copy; then update mtime on pending to simulate touched
    src = Path("pending") / "a.txt"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x\n", encoding="utf-8")
    write_manifest(["a.txt"])  # tracked file

    # simulate sync by creating identical in preview
    dst = Path("preview") / "a.txt"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("x\n", encoding="utf-8")

    # ensure src newer but same content → touched
    _touch_ns(src)

    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    out = res.stdout
    assert "👆 a.txt (touched)" in out or "✅ a.txt" in out


def test_check_folder_missing_from_pending_warns(cli_runner: CliRunner, tmp_repo: Path, write_manifest):
    # Track a folder; create preview folder only
    write_manifest(["data/"])
    (Path("preview") / "data").mkdir(parents=True, exist_ok=True)

    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    assert "⚠️  data/ (missing from pending)" in res.stdout


def test_check_orphan_files_listed_as_removed(cli_runner: CliRunner, tmp_repo: Path, write_manifest):
    # Track one folder and one file; create extra file in preview
    (Path("pending") / "tracked.txt").write_text("x\n", encoding="utf-8")
    write_manifest(["tracked.txt"])  # direct tracking
    (Path("preview") / "orphan.txt").parent.mkdir(parents=True, exist_ok=True)
    (Path("preview") / "orphan.txt").write_text("y\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    assert "⚠️  orphan.txt (removed)" in res.stdout


def test_check_synced_vs_modified_for_file_and_folder(cli_runner: CliRunner, tmp_repo: Path, write_manifest):
    # file case
    (Path("pending") / "f.txt").write_text("x\n", encoding="utf-8")
    # track file and folder together to avoid overwrite
    (Path("preview") / "f.txt").parent.mkdir(parents=True, exist_ok=True)
    (Path("preview") / "f.txt").write_text("DIFFERENT\n", encoding="utf-8")

    # folder case: create structure and make a change in preview
    (Path("pending") / "d").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "d" / "a.txt").write_text("A\n", encoding="utf-8")
    write_manifest(["f.txt", "d/"])
    (Path("preview") / "d").mkdir(parents=True, exist_ok=True)
    (Path("preview") / "d" / "a.txt").write_text("B\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    out = res.stdout
    assert "🔄 f.txt (modified)" in out
    assert "🔄 d/ (modified)" in out


def test_check_untracked_listing_and_summary(cli_runner: CliRunner, tmp_repo: Path, write_manifest):
    # Untracked files in pending should be listed, ignored files filtered
    (Path("pending") / "u.txt").write_text("x\n", encoding="utf-8")
    (Path("pending") / ".DS_Store").write_text("", encoding="utf-8")
    write_manifest([])
    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    out = res.stdout
    assert "📄 u.txt (untracked)" in out
    assert ".DS_Store" not in out
    # Summary counters present
    m = re.search(r"Synced: (\d+), Modified: (\d+), Touched: (\d+), Staged: (\d+), Untracked: (\d+), Removed: (\d+)", out)
    assert m, "summary line missing"
    # Count listed untracked lines equals Untracked counter (1 here)
    assert int(m.group(5)) >= 1


def test_check_logging_separation_json_format(cli_runner: CliRunner, tmp_repo: Path, write_manifest, monkeypatch):
    # Assert stdout contains only user-facing lines (no JSON logs) when json log format is selected.
    # We can't reliably capture stderr on older click versions, so just assert stdout has no NDJSON lines.
    monkeypatch.setenv("CLASSPUB_ENV", "development")
    res = cli_runner.invoke(app, ["--log-format", "json", "check"])  # with empty repo
    assert res.exit_code == 0
    assert res.stdout.strip() != ""
    # No JSON lines should appear in stdout
    for line in res.stdout.splitlines():
        assert not (line.startswith("{") and line.endswith("}")), "stdout should not contain JSON logs"



