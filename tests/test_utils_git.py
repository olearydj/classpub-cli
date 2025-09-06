from __future__ import annotations

from classpub_cli import utils


def test_git_version_ok_no_git(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    ok, ver = utils.git_version_ok()
    assert ok is False
    assert ver == ""


def test_git_version_ok_unparsable(monkeypatch):
    def fake_which(_name):
        return "git"

    def fake_check_output(args, text=True):  # noqa: ARG001
        return "git version unknown"

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.check_output", fake_check_output)
    ok, ver = utils.git_version_ok()
    assert ok is False
    assert ver in ("", "git version unknown")


