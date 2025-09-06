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


