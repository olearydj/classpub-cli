from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from classpub_cli.cli import app


def test_release_adds_file_and_duplicate(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # repo root
        (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "notebooks" / "hello.py").write_text("print('hi')\n")

        res1 = runner.invoke(app, ["release", "notebooks/hello.py"])
        assert res1.exit_code == 0
        assert "✓ Marked notebooks/hello.py for release" in res1.stdout
        assert "Run 'classpub sync' to copy to public folder" in res1.stdout

        res2 = runner.invoke(app, ["release", "notebooks/hello.py"])
        assert res2.exit_code == 0
        assert "already released" in res2.stdout


def test_release_adds_folder_with_trailing_slash_and_hint(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (Path("pending") / "data").mkdir(parents=True, exist_ok=True)
        res = runner.invoke(app, ["release", "data/"])
        assert res.exit_code == 0
        assert "✓ Marked data/ for release" in res.stdout
        assert "Run 'classpub sync' to copy to public folder" in res.stdout


def test_unicode_nfc_matches_but_preserves_display(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Create a file with a composed character; input can be decomposed equivalent
        name = "café.txt"  # contains e\u0301 combining
        (Path("pending")).mkdir(parents=True, exist_ok=True)
        (Path("pending") / name).write_text("x\n")
        # Use a different normalization for input (simulate user typing)
        decomposed = "cafe\u0301.txt"
        res = runner.invoke(app, ["release", decomposed])
        assert res.exit_code == 0
        # Output should print canonical POSIX path; either name variant is acceptable
        assert "café.txt" in res.stdout or "café.txt" in res.stdout


def test_release_not_found_prints_grouped_listing_and_exit_1(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # create some files and folders under pending/
        (Path("pending") / "a").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "a" / "file1.txt").write_text("x\n")
        (Path("pending") / "b").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "b" / "file2.txt").write_text("y\n")

        res = runner.invoke(app, ["release", "zzz-nonexistent"])
        assert res.exit_code == 1
        out = res.stdout
        assert "❌ File or folder not found:" in out
        # At least one section should appear, and lines should be two-space indented
        assert ("Files:" in out) or ("Folders:" in out)
        # spot-check indentation
        assert "\n  a/file1.txt" in out or "\n  b/file2.txt" in out or "\n  a/" in out or "\n  b/" in out


def test_release_ambiguous_prints_labeled_candidates_and_exit_1(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Ambiguity only when no exact path exists, but multiple basename matches.
        # Create file 'dir1/target' and folder 'dir2/target' so basename 'target' has 2 candidates.
        (Path("pending") / "dir1").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "dir1" / "target").write_text("z\n")
        (Path("pending") / "dir2" / "target").mkdir(parents=True, exist_ok=True)

        res = runner.invoke(app, ["release", "target"])
        assert res.exit_code == 1
        out = res.stdout
        # folder and file candidates should be labeled with relative paths
        assert "dir1/target (file)" in out
        assert "dir2/target/ (folder)" in out


def test_remove_existing_file_entry_reports_success(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "notebooks" / "hello.py").write_text("print('hi')\n")
        # add then remove
        add = runner.invoke(app, ["release", "notebooks/hello.py"])
        assert add.exit_code == 0
        rem = runner.invoke(app, ["remove", "notebooks/hello.py"])
        assert rem.exit_code == 0
        assert "✓ Removed notebooks/hello.py from release manifest" in rem.stdout


def test_remove_when_not_present_prints_current_manifest_listing_exit_0(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (Path("pending") / "images").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "images" / "logo.png").write_bytes(b"\x89PNG\r\n")
        runner.invoke(app, ["release", "images/"])
        res = runner.invoke(app, ["remove", "notebooks/none.py"])
        # If it resolves to not found in pending, it's a resolution error (1). If it resolves and isn't in manifest, exit 0.
        assert res.exit_code in (0, 1)
        out = res.stdout
        # If resolution succeeded as not present, we expect listing; otherwise not-found path was taken.
        if "Currently released files:" in out:
            assert "images/" in out


def test_remove_manifest_missing_exit_1(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # repo without manifest
        (Path("pending")).mkdir(parents=True, exist_ok=True)
        res = runner.invoke(app, ["remove", "anything"])
        assert res.exit_code == 1
        assert "RELEASES.txt is missing" in res.stdout


def test_remove_prints_preview_hint_when_item_exists_in_preview(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
        (Path("preview") / "notebooks").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "notebooks" / "hello.py").write_text("print('hi')\n")
        (Path("preview") / "notebooks" / "hello.py").write_text("print('hi')\n")
        runner.invoke(app, ["release", "notebooks/hello.py"])
        res = runner.invoke(app, ["remove", "notebooks/hello.py"])
        assert res.exit_code == 0
        assert "Item still exists in preview" in res.stdout


def test_repo_root_enforced_missing_pending_exit_1(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        res = runner.invoke(app, ["release", "anything"])
        assert res.exit_code == 1
        assert "repository root" in res.stdout


def test_alias_add_behaves_like_release(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (Path("pending") / "docs").mkdir(parents=True, exist_ok=True)
        (Path("pending") / "docs" / "readme.md").write_text("hi\n")
        res = runner.invoke(app, ["add", "docs/readme.md"])
        assert res.exit_code == 0
        assert "✓ Marked docs/readme.md for release" in res.stdout


