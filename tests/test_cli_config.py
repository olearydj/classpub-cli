from __future__ import annotations

from pathlib import Path
from typer.testing import CliRunner

from classpub_cli.cli import app


def test_config_init_creates_file(cli_runner: CliRunner, tmp_repo):
    res = cli_runner.invoke(app, ["config", "init"])
    assert res.exit_code == 0
    path = Path("classpub.toml")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "[general]" in text and "[ignore]" in text


def test_config_init_idempotent(cli_runner: CliRunner, tmp_repo):
    p = Path("classpub.toml")
    p.write_text("# pre\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["config", "init"])
    assert res.exit_code == 0
    assert "already exists" in res.stdout


def test_sync_removal_assume_yes_from_config(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange: one tracked file, and create an orphan in preview
    (Path("pending") / "a.txt").write_text("x\n", encoding="utf-8")
    write_manifest(["a.txt"])  # tracked
    # First sync to create preview copy
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    # Now remove it from manifest so it becomes an orphan and write config to auto-yes
    (Path("pending")/"RELEASES.txt").write_text("\n", encoding="utf-8")
    Path("classpub.toml").write_text("""
[general]
assume_yes = true
""".strip()+"\n", encoding="utf-8")

    # Run sync without --yes; should auto-remove due to config
    res = cli_runner.invoke(app, ["sync"])
    assert res.exit_code == 0
    assert "Sync complete" in res.stdout


def test_check_respects_custom_ignore_patterns(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Add a custom ignored file and directory pattern
    Path("classpub.toml").write_text("""
[ignore]
patterns = [
  "thumbs.db",
  "node_modules/",
]
""".strip()+"\n", encoding="utf-8")
    # Create matching artifacts under pending
    (Path("pending")/"thumbs.db").write_text("x\n", encoding="utf-8")
    nm = Path("pending")/"node_modules"
    nm.mkdir(parents=True, exist_ok=True)
    (nm/"pkg.json").write_text("{}\n", encoding="utf-8")

    # Create one real file to ensure check prints something non-ignored
    (Path("pending")/"real.txt").write_text("x\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    out = res.stdout
    assert "thumbs.db" not in out
    assert "node_modules" not in out
    assert "real.txt" in out


def test_validate_strict_escalates_warnings(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create an orphan preview folder by making preview/ exist with a subfolder
    (Path("preview")/"orphan").mkdir(parents=True, exist_ok=True)
    # Strict mode enabled
    Path("classpub.toml").write_text("""
[general]
strict = true
""".strip()+"\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["validate"])
    # No structural errors, but warnings exist; strict should make exit 1
    assert res.exit_code == 1


def test_config_init_outside_repo_root_errors(cli_runner: CliRunner, tmp_path):
    # No pending/ directory here
    with cli_runner.isolated_filesystem(temp_dir=tmp_path):
        res = cli_runner.invoke(app, ["config", "init"])
        assert res.exit_code == 1
        assert "Run from the repository root" in res.stdout


def test_cli_yes_overrides_config_false(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange: create an orphan by syncing then clearing manifest
    (Path("pending") / "b.txt").write_text("x\n", encoding="utf-8")
    write_manifest(["b.txt"])  # tracked
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    # Config says assume_yes=false
    Path("classpub.toml").write_text("""
[general]
assume_yes = false
""".strip()+"\n", encoding="utf-8")
    # Remove from manifest to create orphans
    (Path("pending")/"RELEASES.txt").write_text("\n", encoding="utf-8")
    # Using --yes should proceed regardless of config false
    res = cli_runner.invoke(app, ["sync", "--yes"])  # no prompt path
    assert res.exit_code == 0
    assert "Sync complete" in res.stdout


def test_ignore_patterns_affect_diff_to_md_and_orphans(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create a directory that should be ignored and a file pattern to ignore
    Path("classpub.toml").write_text("""
[ignore]
patterns = [
  "node_modules/",
  "*.tmp",
]
""".strip()+"\n", encoding="utf-8")
    nm = Path("pending")/"node_modules"
    nm.mkdir(parents=True, exist_ok=True)
    (nm/"pkg.json").write_text("{}\n", encoding="utf-8")
    # A tracked folder with a .tmp file inside should not appear in diff/orphans
    base = Path("pending")/"proj"
    (base).mkdir(parents=True, exist_ok=True)
    (base/"keep.md").write_text("k\n", encoding="utf-8")
    (base/"skip.tmp").write_text("tmp\n", encoding="utf-8")
    write_manifest(["proj/"])

    # First sync
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    # Modify pending keep.md so diff has something; ensure skip.tmp is ignored
    (base/"keep.md").write_text("K2\n", encoding="utf-8")
    r = cli_runner.invoke(app, ["diff", "proj/"])
    assert r.exit_code == 0
    out = r.stdout
    assert "skip.tmp" not in out
    # to-md should not attempt to walk node_modules or emit anything for .tmp
    res_to_md = cli_runner.invoke(app, ["to-md"])  # default source=pending
    assert res_to_md.exit_code == 0
    assert not any(p.name.endswith(".tmp") for p in (Path("pending")/"md").rglob("*"))

    # Orphans: create an orphan .tmp under preview; should be ignored
    prev_tmp = Path("preview")/"proj"/"orphan.tmp"
    prev_tmp.parent.mkdir(parents=True, exist_ok=True)
    prev_tmp.write_text("x\n", encoding="utf-8")
    res_check = cli_runner.invoke(app, ["check"])
    assert res_check.exit_code == 0
    assert "orphan.tmp" not in res_check.stdout


def test_ignore_extend_not_replace_and_malformed_config(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Empty list should still keep defaults (e.g., .DS_Store filtered)
    Path("classpub.toml").write_text("""
[ignore]
patterns = []
""".strip()+"\n", encoding="utf-8")
    (Path("pending")/".DS_Store").write_text("x\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    assert ".DS_Store" not in res.stdout

    # Malformed config (bad TOML) should log error and default to built-ins
    Path("classpub.toml").write_text("this = [bad\n", encoding="utf-8")
    # Run a command that loads config; it should not crash and should still filter defaults
    res2 = cli_runner.invoke(app, ["check"])
    assert res2.exit_code == 0


def test_directory_and_path_pattern_semantics(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Configure: ignore a directory by trailing slash and a path-matching pattern with '/'
    Path("classpub.toml").write_text("""
[ignore]
patterns = [
  "venv/",
  "build/**/*.tmp",
]
""".strip()+"\n", encoding="utf-8")
    # Create matching dirs/files
    venv = Path("pending")/"venv"/"lib"
    venv.mkdir(parents=True, exist_ok=True)
    (venv/"ignore.me").write_text("x\n", encoding="utf-8")
    build = Path("pending")/"build"/"sub"
    build.mkdir(parents=True, exist_ok=True)
    (build/"a.tmp").write_text("t\n", encoding="utf-8")
    (build/"b.txt").write_text("b\n", encoding="utf-8")
    (Path("pending")/"keep.txt").write_text("k\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["check"])
    assert res.exit_code == 0
    out = res.stdout
    # ensure ignored items absent; non-ignored present
    assert "ignore.me" not in out
    assert "a.tmp" not in out
    assert "b.txt" in out
    assert "keep.txt" in out

