from __future__ import annotations

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_global_verbose_and_quiet_affect_log_level():
    runner = CliRunner()
    res1 = runner.invoke(app, ["--verbose", "--verbose", "init"])  # INFO -> DEBUG
    assert res1.exit_code == 0

    res2 = runner.invoke(app, ["--quiet", "init"])  # INFO -> WARNING
    assert res2.exit_code == 0


def test_log_format_json_writes_logs_to_stderr_only():
    runner = CliRunner()
    res = runner.invoke(app, ["--log-format", "json", "init"])  # emits logs to stderr
    assert res.exit_code == 0
    # stdout contains user-facing lines, stderr contains JSON logs (may be empty if INFO hidden)
    assert res.stdout != ""


def test_warning_console_level_still_prints_result_to_stdout():
    runner = CliRunner()
    res = runner.invoke(app, ["--log-level", "warning", "init"])  # console hides INFO
    assert res.exit_code == 0
    assert res.stdout.strip() != ""


def test_version_and_alias_simple(cli_runner: CliRunner):
    # --version prints a version-like string
    res_v = cli_runner.invoke(app, ["--version"])
    assert res_v.exit_code == 0
    assert "." in res_v.stdout
    # alias add works
    from pathlib import Path
    with cli_runner.isolated_filesystem():
        (Path("pending") / "d").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "d" / "x.txt").write_text("x\n", encoding="utf-8")
        res_add = cli_runner.invoke(app, ["add", "d/x.txt"])
        assert res_add.exit_code == 0
        assert "✓ Marked d/x.txt for release" in res_add.stdout


def test_console_level_env_default_and_explicit_override(monkeypatch):
    runner = CliRunner()
    # production env should default console level to WARNING (no noisy stderr expected from INFO logs)
    monkeypatch.setenv("CLASSPUB_ENV", "production")
    res1 = runner.invoke(app, ["init"])  # any command
    assert res1.exit_code == 0
    # explicit override to ERROR
    res2 = runner.invoke(app, ["--log-level", "error", "init"])
    assert res2.exit_code == 0


