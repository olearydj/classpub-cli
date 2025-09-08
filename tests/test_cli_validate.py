from __future__ import annotations

import builtins
from contextlib import contextmanager
from typing import Iterator

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_validate_happy_path(monkeypatch):
    runner = CliRunner()

    # Simulate git present and modern
    import classpub_cli.utils as utils

    monkeypatch.setattr(utils, "git_version_ok", lambda: (True, "2.42.0"))
    # Simulate all deps present by no-op import
    monkeypatch.setattr(utils, "check_python_deps", lambda: [])

    res = runner.invoke(app, ["validate"])  # emits OK lines
    assert res.exit_code == 0
    assert "Dependencies OK" in res.stdout
    assert "Git OK" in res.stdout


def test_validate_missing_dep(monkeypatch):
    runner = CliRunner()
    import classpub_cli.utils as utils

    monkeypatch.setattr(utils, "check_python_deps", lambda: ["nbconvert"])  # one missing
    res = runner.invoke(app, ["validate"])  # should fail
    assert res.exit_code == 1
    assert "Missing dependency" in res.stdout


def test_validate_git_too_old(monkeypatch):
    runner = CliRunner()
    import classpub_cli.utils as utils

    monkeypatch.setattr(utils, "check_python_deps", lambda: [])
    monkeypatch.setattr(utils, "git_version_ok", lambda: (False, "2.18.0"))
    res = runner.invoke(app, ["validate"])  # should fail
    assert res.exit_code == 1
    assert "Git >= 2.20" in res.stdout


def _deps_ok(monkeypatch):
    import classpub_cli.utils as utils
    monkeypatch.setattr(utils, "check_python_deps", lambda: [])
    monkeypatch.setattr(utils, "git_version_ok", lambda: (True, "2.42.0"))


def test_validate_preview_symlink_error(cli_runner: CliRunner, tmp_repo, monkeypatch):
    _deps_ok(monkeypatch)
    # Create manifest to avoid manifest-missing error
    (tmp_repo / "pending" / "RELEASES.txt").write_text("", encoding="utf-8")
    # Create preview as a symlink
    target = tmp_repo / "_tgt"
    target.mkdir(exist_ok=True)
    (tmp_repo / "preview").symlink_to(target)

    res = cli_runner.invoke(app, ["validate"])
    assert res.exit_code == 1
    assert "preview/ must not be a symlink" in res.stdout


def test_validate_mixed_separators_warning(cli_runner: CliRunner, tmp_repo, monkeypatch):
    _deps_ok(monkeypatch)
    # Prepare pending and manifest with Windows-style separators
    (tmp_repo / "pending").mkdir(exist_ok=True)
    (tmp_repo / "pending" / "RELEASES.txt").write_text("nbs\\hello.ipynb\n", encoding="utf-8")
    # Do not create preview to also get the preview-missing warning in another test; here we create it
    (tmp_repo / "preview").mkdir(exist_ok=True)

    res = cli_runner.invoke(app, ["validate"])
    assert res.exit_code == 0
    out = res.stdout
    assert "Manifest uses Windows separators" in out


def test_validate_manifest_folder_presence_warnings(cli_runner: CliRunner, tmp_repo, monkeypatch):
    _deps_ok(monkeypatch)
    # Manifest folder that is missing in pending and preview
    (tmp_repo / "pending").mkdir(exist_ok=True)
    (tmp_repo / "pending" / "RELEASES.txt").write_text("data/\n", encoding="utf-8")
    (tmp_repo / "preview").mkdir(exist_ok=True)

    res = cli_runner.invoke(app, ["validate"])
    assert res.exit_code == 0
    out = res.stdout
    assert "data/ (missing from pending)" in out
    assert "preview/data/ is missing" in out


def test_validate_orphan_preview_folder(cli_runner: CliRunner, tmp_repo, monkeypatch):
    _deps_ok(monkeypatch)
    # No tracked entries; orphan folder appears under preview
    (tmp_repo / "pending").mkdir(exist_ok=True)
    (tmp_repo / "pending" / "RELEASES.txt").write_text("", encoding="utf-8")
    (tmp_repo / "preview" / "orphan").mkdir(parents=True, exist_ok=True)
    (tmp_repo / "preview" / "orphan" / "x.txt").write_text("x\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["validate"])
    assert res.exit_code == 0
    assert "Orphan preview folder: preview/orphan/" in res.stdout


def test_validate_summary_counts_two_warnings(cli_runner: CliRunner, tmp_repo, monkeypatch):
    _deps_ok(monkeypatch)
    # Ensure doctor checks do not add extra warnings in CI (git identity/nbdime)
    import subprocess as _sp
    def _check_output_ok(args, text=True):  # noqa: ANN001
        cmd = " ".join(args)
        if "user.name" in cmd:
            return "CI User"
        if "user.email" in cmd:
            return "ci@example.com"
        if "diff.jupyternotebook.tool" in cmd:
            return "nbdime"
        return ""
    monkeypatch.setattr(_sp, "check_output", _check_output_ok)
    # Prepare: pending exists; manifest has mixed separators; preview missing
    (tmp_repo / "pending").mkdir(exist_ok=True)
    (tmp_repo / "pending" / "RELEASES.txt").write_text("a\\b\\c.txt\n", encoding="utf-8")
    # Do not create preview/ → warning

    res = cli_runner.invoke(app, ["validate"])
    assert res.exit_code == 0
    assert "Validate complete: 0 errors, 2 warnings" in res.stdout


def test_validate_doctor_warnings(cli_runner: CliRunner, tmp_repo, monkeypatch):
    _deps_ok(monkeypatch)
    # Create minimal repo structure but leave preview missing to avoid extra warnings
    (tmp_repo / "pending").mkdir(exist_ok=True)
    (tmp_repo / "pending" / "RELEASES.txt").write_text("", encoding="utf-8")

    # Mock subprocess calls in validate for git config and nbdime detection
    import subprocess as _sp
    def _check_output(args, text=True):  # noqa: ANN001
        cmd = " ".join(args)
        if "user.name" in cmd:
            return ""  # empty to trigger warning
        if "user.email" in cmd:
            return ""  # empty to trigger warning
        if "diff.jupyternotebook.tool" in cmd:
            raise Exception("not set")
        return ""

    monkeypatch.setattr(_sp, "check_output", _check_output)

    res = cli_runner.invoke(app, ["validate"])
    assert res.exit_code == 0
    out = res.stdout
    assert "Git user.name/email not configured globally" in out or "Unable to read git user.name/email" in out
    assert "Nbdime git integration not detected" in out


