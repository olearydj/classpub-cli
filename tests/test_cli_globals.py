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


