from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_install_dry_run(cli_runner: CliRunner, tmp_repo: Path, monkeypatch):
    # Ensure clean tmp repo with only pending/
    (tmp_repo / "pending").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_repo)

    res = cli_runner.invoke(app, ["setup", "--dry-run"])
    assert res.exit_code == 0
    out = res.stdout
    assert "Wrote justfile" in out
    assert "Setup complete" in out


def test_install_writes_files_and_backup(cli_runner: CliRunner, tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    # Pre-create a justfile to force backup path
    (tmp_repo / "justfile").write_text("default:\n    @echo hi\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["setup", "--skip-ci"])  # real write
    assert res.exit_code == 0

    # justfile replaced and backup created
    jf = tmp_repo / "justfile"
    assert jf.exists()
    backups = list(tmp_repo.glob("justfile.bak-*"))
    assert backups, "expected a justfile.bak-* backup"

    # directories and files
    assert (tmp_repo / "pending").exists()
    # manifest created if missing
    assert (tmp_repo / "pending" / "RELEASES.txt").exists()
    # classpub.toml created
    assert (tmp_repo / "classpub.toml").exists()
    # .gitignore created or merged
    assert (tmp_repo / ".gitignore").exists()
    body = (tmp_repo / ".gitignore").read_text(encoding="utf-8")
    for line in ("preview/", ".ipynb_checkpoints/", "pending/md/"):
        assert line in body


def test_install_writes_workflow_unless_skipped(cli_runner: CliRunner, tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    res = cli_runner.invoke(app, ["setup"])  # write with CI
    assert res.exit_code == 0
    wf = tmp_repo / ".github" / "workflows" / "publish-public.yml"
    assert wf.exists()
    # contains placeholder requiring user edit
    assert "OWNER/REPO" in wf.read_text(encoding="utf-8")


def test_setup_generates_help_recipe(cli_runner: CliRunner, tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    res = cli_runner.invoke(app, ["setup", "--skip-ci"])  # real write
    assert res.exit_code == 0
    jf = (tmp_repo / "justfile").read_text(encoding="utf-8")
    assert "help:" in jf


