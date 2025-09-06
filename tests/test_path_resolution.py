from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from classpub_cli.cli import app


def _make_tree(tmp: Path):
    (tmp / "pending" / "a").mkdir(parents=True, exist_ok=True)
    (tmp / "pending" / "a" / "foo.txt").write_text("x\n")
    (tmp / "pending" / "b").mkdir(parents=True, exist_ok=True)
    (tmp / "pending" / "b" / "bar.txt").write_text("y\n")


def test_absolute_path_under_pending_ok(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_tree(Path.cwd())
        abs_file = (Path.cwd() / "pending" / "a" / "foo.txt").resolve()
        res = runner.invoke(app, ["release", str(abs_file)])
        assert res.exit_code == 0
        assert "✓ Marked a/foo.txt for release" in res.stdout


def test_absolute_path_outside_pending_errors(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # create pending to satisfy repo-root, but pass outside path
        (Path("pending")).mkdir(parents=True, exist_ok=True)
        outside = (Path.cwd().parent / "not_in_repo.txt").resolve()
        res = runner.invoke(app, ["release", str(outside)])
        assert res.exit_code == 1
        assert "inside pending/" in res.stdout


def test_pending_prefix_is_stripped(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_tree(Path.cwd())
        res = runner.invoke(app, ["release", "pending/a/foo.txt"])
        assert res.exit_code == 0
        assert "a/foo.txt" in res.stdout


def test_windows_style_separators_are_accepted(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_tree(Path.cwd())
        res = runner.invoke(app, ["release", "pending\\a\\foo.txt"])  # backslashes in input
        assert res.exit_code == 0
        assert "a/foo.txt" in res.stdout


def test_relative_exact_folder_match_trailing_slash_optional(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_tree(Path.cwd())
        res1 = runner.invoke(app, ["release", "a/"])
        assert res1.exit_code == 0
        assert "a/ for release" in res1.stdout
        res2 = runner.invoke(app, ["release", "b"])  # folder without trailing slash
        assert res2.exit_code == 0
        assert "b/ for release" in res2.stdout


def test_trailing_slash_on_file_is_tolerated_and_marks_file(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _make_tree(Path.cwd())
        res = runner.invoke(app, ["release", "a/foo.txt/"])
        assert res.exit_code == 0
        assert "✓ Marked a/foo.txt for release" in res.stdout or "already released" in res.stdout


def test_basename_disambiguation_lists_both(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Ambiguity only when no exact path exists.
        # Create file 'x/shared' and folder 'y/shared' so basename 'shared' has two candidates.
        (Path("pending") / "x").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "x" / "shared").write_text("content\n")
        (Path("pending") / "y" / "shared").mkdir(parents=True, exist_ok=True)
        res = runner.invoke(app, ["release", "shared"])
        assert res.exit_code == 1
        out = res.stdout
        assert "x/shared (file)" in out
        assert "y/shared/ (folder)" in out


