from __future__ import annotations

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_version_flag_prints_version():
    runner = CliRunner()
    res = runner.invoke(app, ["--version"])  # early exit
    assert res.exit_code == 0
    assert res.stdout.strip() != ""
    # Basic semantic: contains dots typical of semver or fallback
    assert "." in res.stdout.strip()


def test_version_fallback(monkeypatch):
    # Simulate PackageNotFoundError by calling __getattr__ directly with a monkeypatched version()
    import classpub_cli.__init__ as init_mod

    def raise_pkg_not_found(_name):
        raise init_mod.PackageNotFoundError  # type: ignore[misc]

    monkeypatch.setattr(init_mod, "version", raise_pkg_not_found, raising=True)
    # Direct call into __getattr__ avoids needing to delete attributes from the module
    assert init_mod.__getattr__("__version__") == "0.0.0"


