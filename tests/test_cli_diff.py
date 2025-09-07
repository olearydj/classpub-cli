from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from classpub_cli.cli import app


def _has_git_diff_markers(text: str) -> bool:
    # Be flexible across git versions/platforms
    return ("diff --git" in text) or ("+++ " in text and "--- " in text)


def test_diff_no_arg_text_file_changed_prints_git_diff(cli_runner: CliRunner, tmp_repo, write_manifest):
    write_manifest(["notes.txt"])  # track file directly
    # Create initial file and sync to create preview copy
    (Path("pending") / "notes.txt").write_text("a\n", encoding="utf-8")
    r1 = cli_runner.invoke(app, ["sync", "--yes"])  # create preview baseline
    assert r1.exit_code == 0

    # Modify pending
    (Path("pending") / "notes.txt").write_text("b\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["diff"])  # no-arg mode
    assert res.exit_code == 0
    assert "📊 Diff: preview vs pending (tracked files only)" in res.stdout
    # Expect a git diff body
    assert _has_git_diff_markers(res.stdout)


def test_diff_no_arg_notebook_changed_prints_output(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create a minimal ipynb (as plain JSON) and sync
    nb = Path("pending") / "notebooks" / "demo.ipynb"
    nb.parent.mkdir(parents=True, exist_ok=True)
    nb.write_text("{\n  \"cells\": [], \n  \"metadata\": {}, \n  \"nbformat\": 4, \n  \"nbformat_minor\": 5\n}\n", encoding="utf-8")
    write_manifest(["notebooks/demo.ipynb"])  # track file directly
    r1 = cli_runner.invoke(app, ["sync", "--yes"])  # create preview baseline
    assert r1.exit_code == 0

    # Change pending notebook minimally
    nb.write_text("{\n  \"cells\": [{\"cell_type\": \"markdown\", \"metadata\": {}, \"source\": [\"x\"]}], \n  \"metadata\": {}, \n  \"nbformat\": 4, \n  \"nbformat_minor\": 5\n}\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["diff"])  # no-arg mode
    assert res.exit_code == 0
    assert "📊 Diff: preview vs pending (tracked files only)" in res.stdout
    # Body should not be empty; do not assert specific formatting
    assert len([ln for ln in res.stdout.splitlines() if ln.strip()]) > 1


def test_diff_no_arg_no_differences_prints_summary_line(cli_runner: CliRunner, tmp_repo, write_manifest):
    write_manifest(["a.txt"])  # track
    (Path("pending") / "a.txt").write_text("x\n", encoding="utf-8")
    r1 = cli_runner.invoke(app, ["sync", "--yes"])  # baseline both sides equal
    assert r1.exit_code == 0
    res = cli_runner.invoke(app, ["diff"])  # no changes
    assert res.exit_code == 0
    out = res.stdout
    assert "📊 Diff: preview vs pending (tracked files only)" in out
    assert "✅ No differences found between tracked files" in out


def test_diff_no_arg_ignores_side_only_items(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Track file that exists only in pending; no preview created
    write_manifest(["alpha.txt"])  # track file
    (Path("pending") / "alpha.txt").write_text("x\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["diff"])  # no-arg mode
    assert res.exit_code == 0
    out = res.stdout
    assert "📊 Diff: preview vs pending (tracked files only)" in out
    assert "✅ No differences found between tracked files" in out


def test_diff_item_file_both_sides_changed(cli_runner: CliRunner, tmp_repo, write_manifest):
    write_manifest(["file.txt"])  # track
    (Path("pending") / "file.txt").write_text("1\n", encoding="utf-8")
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    (Path("pending") / "file.txt").write_text("2\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["diff", "file.txt"])  # item mode
    assert res.exit_code == 0
    assert _has_git_diff_markers(res.stdout)


def test_diff_item_file_only_in_pending_message(cli_runner: CliRunner, tmp_repo, write_manifest):
    write_manifest(["lonely.txt"])  # track
    (Path("pending") / "lonely.txt").write_text("x\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["diff", "lonely.txt"])  # preview missing
    assert res.exit_code == 0
    assert "ℹ️  lonely.txt exists in pending but not in preview" in res.stdout


def test_diff_item_folder_summary_sections_and_paths(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange both sides with baseline, then introduce Added/Removed/Changed
    base = Path("pending") / "data"
    base.mkdir(parents=True, exist_ok=True)
    (base / "a.txt").write_text("a\n", encoding="utf-8")
    (base / "b.txt").write_text("b\n", encoding="utf-8")
    write_manifest(["data/"])
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    # Added in pending
    (base / "c.txt").write_text("c\n", encoding="utf-8")
    # Removed from pending (still in preview)
    (base / "b.txt").unlink()
    # Changed in pending
    (base / "a.txt").write_text("aa\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["diff", "data/"])
    assert res.exit_code == 0
    out = res.stdout.splitlines()
    assert any(line.startswith("📁 data/ (folder has changes)") for line in out)
    assert any(line.strip() == "Added:" for line in out)
    assert any(line.strip() == "Removed:" for line in out)
    assert any(line.strip() == "Changed:" for line in out)
    # Paths are relative under the folder
    assert any(line.strip() == "c.txt" or line.strip() == "  c.txt" for line in out)
    assert any(line.strip() == "b.txt" or line.strip() == "  b.txt" for line in out)
    assert any(line.strip() == "a.txt" or line.strip() == "  a.txt" for line in out)


def test_diff_item_folder_no_changes_prints_nothing(cli_runner: CliRunner, tmp_repo, write_manifest):
    (Path("pending") / "z").mkdir(parents=True, exist_ok=True)
    write_manifest(["z/"])
    # Create preview baseline with sync (empty folder both sides)
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    res = cli_runner.invoke(app, ["diff", "z/"])
    assert res.exit_code == 0
    # No sections/headings expected when there are no changes
    assert res.stdout.strip() == ""


def test_diff_resolution_not_found_lists_grouped_entries(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create some files/folders under pending for listing
    (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "notebooks" / "h1.py").write_text("x\n", encoding="utf-8")
    (Path("pending") / "data").mkdir(parents=True, exist_ok=True)
    write_manifest(["notebooks/h1.py", "data/"])

    res = cli_runner.invoke(app, ["diff", "missing.txt"])  # not found token
    assert res.exit_code == 1
    out = res.stdout
    assert "❌ File or folder not found: missing.txt" in out
    assert "Files:" in out
    assert "Folders:" in out


def test_diff_resolution_ambiguous_lists_candidates(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create two files with the same basename in different folders → basename ambiguity
    (Path("pending") / "d1").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "d2").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "d1" / "hello.txt").write_text("x\n", encoding="utf-8")
    (Path("pending") / "d2" / "hello.txt").write_text("y\n", encoding="utf-8")
    write_manifest(["d1/", "d2/"])  # not required but ok
    res = cli_runner.invoke(app, ["diff", "hello.txt"])  # ambiguous by basename
    assert res.exit_code == 1
    out = res.stdout
    assert "❌ Ambiguous item: hello.txt" in out
    # Expect both candidates listed with (file)
    assert "d1/hello.txt (file)" in out or "d2/hello.txt (file)" in out


def test_diff_git_version_insufficient_fails_gracefully(cli_runner: CliRunner, tmp_repo, monkeypatch, write_manifest):
    # Arrange a trivial tracked file
    write_manifest(["g.txt"])  # track
    (Path("pending") / "g.txt").write_text("1\n", encoding="utf-8")
    # Force git check to fail
    monkeypatch.setattr("classpub_cli.diff._ensure_git_ready", lambda: False)
    res = cli_runner.invoke(app, ["diff"])  # no-arg
    assert res.exit_code == 1
    assert "❌ Git >= 2.20 required for diff" in res.stdout


def test_diff_item_side_only_messages(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Track a file and a folder, create side-only conditions and assert messages
    (Path("pending") / "onlyp.txt").write_text("x\n", encoding="utf-8")
    write_manifest(["onlyp.txt"])  # tracked file
    # For folder: tracked but exists only in preview
    (Path("preview") / "onlyq").mkdir(parents=True, exist_ok=True)
    write_manifest(["onlyq/"],)

    # File exists only in pending
    r1 = cli_runner.invoke(app, ["diff", "onlyp.txt"])
    assert r1.exit_code == 0
    assert "ℹ️  onlyp.txt exists in pending but not in preview" in r1.stdout

    # Folder exists only in preview
    r2 = cli_runner.invoke(app, ["diff", "onlyq/"])
    assert r2.exit_code == 0
    assert "ℹ️  onlyq/ exists in preview but not in pending" in r2.stdout


def test_diff_folder_summary_ignores_filtered_and_symlinks(cli_runner: CliRunner, tmp_repo, write_manifest):
    base = Path("pending") / "filt"
    base.mkdir(parents=True, exist_ok=True)
    # Create ignored artifacts and one real file
    (base / ".DS_Store").write_text("x\n", encoding="utf-8")
    (base / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    (base / "keep.txt").write_text("k\n", encoding="utf-8")
    write_manifest(["filt/"])
    # Create preview baseline via sync
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    # Remove keep.txt from preview to appear in Removed; add another in pending to appear in Added
    (Path("preview") / "filt" / "keep.txt").unlink()
    (base / "new.txt").write_text("n\n", encoding="utf-8")
    # Create an ignored checkpoints directory
    (base / ".ipynb_checkpoints").mkdir(parents=True, exist_ok=True)
    (base / ".ipynb_checkpoints" / "junk.ipynb").write_text("{}\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["diff", "filt/"])
    assert res.exit_code == 0
    out = res.stdout
    # Ignored names should not appear
    assert ".DS_Store" not in out
    assert ".gitignore" not in out
    assert ".ipynb_checkpoints" not in out


def test_diff_folder_summary_truncates_sections_at_200(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create preview empty, pending with many files
    base = Path("pending") / "big"
    base.mkdir(parents=True, exist_ok=True)
    write_manifest(["big/"])
    # Create preview folder baseline
    (Path("preview") / "big").mkdir(parents=True, exist_ok=True)
    for i in range(205):
        (base / f"f{i:03d}.txt").write_text("x\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["diff", "big/"])
    assert res.exit_code == 0
    out_lines = res.stdout.splitlines()
    # Should list exactly 200 entries under Added: then a (+5 more) line
    assert any(ln.strip() == "Added:" for ln in out_lines)
    assert any(ln.strip() == "(+5 more)" for ln in out_lines)


def test_diff_no_arg_tracked_folder_only_pending_suppresses_info_prints_no_differences(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Manifest tracks data/; pending has files but preview missing
    base = Path("pending") / "data"
    base.mkdir(parents=True, exist_ok=True)
    (base / "a.txt").write_text("x\n", encoding="utf-8")
    (base / "b.txt").write_text("y\n", encoding="utf-8")
    write_manifest(["data/"])
    res = cli_runner.invoke(app, ["diff"])  # no-arg
    assert res.exit_code == 0
    out = res.stdout
    assert "📊 Diff: preview vs pending (tracked files only)" in out
    # Should not print side-only info messages in no-arg mode
    assert "exists in pending but not in preview" not in out
    assert "✅ No differences found between tracked files" in out


def test_diff_no_arg_tracked_folder_only_preview_suppresses_info_prints_no_differences(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Manifest tracks img/; preview has folder only
    (Path("preview") / "img").mkdir(parents=True, exist_ok=True)
    write_manifest(["img/"])
    res = cli_runner.invoke(app, ["diff"])  # no-arg
    assert res.exit_code == 0
    out = res.stdout
    assert "📊 Diff: preview vs pending (tracked files only)" in out
    assert "exists in preview but not in pending" not in out
    assert "✅ No differences found between tracked files" in out


def test_diff_item_folder_only_preview_message(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Manifest tracks docs/; preview has folder only
    (Path("preview") / "docs").mkdir(parents=True, exist_ok=True)
    write_manifest(["docs/"])
    res = cli_runner.invoke(app, ["diff", "docs/"])
    assert res.exit_code == 0
    assert "ℹ️  docs/ exists in preview but not in pending" in res.stdout


def test_diff_no_arg_with_json_log_format_keeps_diff_on_stdout(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange changed file
    write_manifest(["j.txt"])  # track
    (Path("pending") / "j.txt").write_text("1\n", encoding="utf-8")
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    (Path("pending") / "j.txt").write_text("2\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["--log-format", "json", "diff"])  # JSON logs to stderr; diff stays on stdout
    assert res.exit_code == 0
    assert _has_git_diff_markers(res.stdout)


def test_diff_folder_removed_section_truncates_at_200(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Make src empty and dst with many files → all should be Removed
    (Path("pending") / "rem").mkdir(parents=True, exist_ok=True)
    dst_dir = Path("preview") / "rem"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for i in range(205):
        (dst_dir / f"g{i:03d}.txt").write_text("z\n", encoding="utf-8")
    write_manifest(["rem/"])
    res = cli_runner.invoke(app, ["diff", "rem/"])
    assert res.exit_code == 0
    out_lines = res.stdout.splitlines()
    assert any(ln.strip() == "Removed:" for ln in out_lines)
    assert any(ln.strip() == "(+5 more)" for ln in out_lines)


def test_diff_folder_changed_section_truncates_at_200(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create 205 files both sides but with different contents → all Changed
    src_dir = Path("pending") / "chg"
    dst_dir = Path("preview") / "chg"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for i in range(205):
        (src_dir / f"c{i:03d}.txt").write_text("A\n", encoding="utf-8")
        (dst_dir / f"c{i:03d}.txt").write_text("B\n", encoding="utf-8")
    write_manifest(["chg/"])
    res = cli_runner.invoke(app, ["diff", "chg/"])
    assert res.exit_code == 0
    out_lines = res.stdout.splitlines()
    assert any(ln.strip() == "Changed:" for ln in out_lines)
    assert any(ln.strip() == "(+5 more)" for ln in out_lines)


def test_diff_folder_summary_skips_symlinks(cli_runner: CliRunner, tmp_repo, write_manifest):
    base = Path("pending") / "sym"
    base.mkdir(parents=True, exist_ok=True)
    (base / "real.txt").write_text("r\n", encoding="utf-8")
    # Create a symlink if platform allows
    try:
        (base / "link.txt").symlink_to("real.txt")
    except Exception:
        pass
    # Create preview with only real.txt
    (Path("preview") / "sym").mkdir(parents=True, exist_ok=True)
    (Path("preview") / "sym" / "real.txt").write_text("rr\n", encoding="utf-8")
    write_manifest(["sym/"])
    res = cli_runner.invoke(app, ["diff", "sym/"])
    assert res.exit_code == 0
    out = res.stdout
    # We should not see the symlink name; only real.txt may appear (as Changed or Removed/Added)
    assert "link.txt" not in out


def test_diff_no_arg_multiple_entries_file_and_folder_combined_output(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange: one tracked file and one tracked folder
    (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "notebooks" / "a.py").write_text("a\n", encoding="utf-8")
    (Path("pending") / "data").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "data" / "x.txt").write_text("x\n", encoding="utf-8")
    write_manifest(["notebooks/a.py", "data/"])
    # Initial sync to create baseline
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    # Modify both
    (Path("pending") / "notebooks" / "a.py").write_text("aa\n", encoding="utf-8")
    (Path("pending") / "data" / "x.txt").write_text("xx\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["diff"])  # no-arg
    assert res.exit_code == 0
    out = res.stdout
    # Header appears
    assert "📊 Diff: preview vs pending (tracked files only)" in out
    # File diff body present
    assert _has_git_diff_markers(out)
    # Folder summary present
    assert "📁 data/ (folder has changes)" in out


def test_diff_item_folder_only_pending_message(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Track a folder that exists only in pending
    base = Path("pending") / "onlyp"
    base.mkdir(parents=True, exist_ok=True)
    (base / "f.txt").write_text("z\n", encoding="utf-8")
    write_manifest(["onlyp/"])
    res = cli_runner.invoke(app, ["diff", "onlyp/"])
    assert res.exit_code == 0
    assert "ℹ️  onlyp/ exists in pending but not in preview" in res.stdout


def test_diff_no_arg_ignores_changes_for_removed_manifest_entries(cli_runner: CliRunner, tmp_repo, write_manifest, read_manifest_lines):
    # Track two entries and sync
    (Path("pending") / "f1.txt").write_text("1\n", encoding="utf-8")
    (Path("pending") / "f2.txt").write_text("2\n", encoding="utf-8")
    write_manifest(["f1.txt", "f2.txt"])  # both tracked
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0

    # Remove one from manifest, then modify it
    # Rewrite manifest to contain only f1.txt
    (Path("pending") / "RELEASES.txt").write_text("f1.txt\n", encoding="utf-8")
    (Path("pending") / "f2.txt").write_text("22\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["diff"])  # no-arg
    assert res.exit_code == 0
    out = res.stdout
    # Should not contain any diff for f2.txt
    assert "f2.txt" not in out
    # But should contain diff markers for f1.txt if changed; ensure header still shown
    assert "📊 Diff: preview vs pending (tracked files only)" in out


def test_diff_item_accepts_pending_prefixed_file(cli_runner: CliRunner, tmp_repo, write_manifest):
    (Path("pending") / "pf.txt").write_text("a\n", encoding="utf-8")
    write_manifest(["pf.txt"])  # track
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    (Path("pending") / "pf.txt").write_text("b\n", encoding="utf-8")

    r1 = cli_runner.invoke(app, ["diff", "pf.txt"])  # plain
    r2 = cli_runner.invoke(app, ["diff", "pending/pf.txt"])  # prefixed
    assert r1.exit_code == 0 and r2.exit_code == 0
    assert _has_git_diff_markers(r1.stdout)
    assert _has_git_diff_markers(r2.stdout)


def test_diff_item_accepts_pending_prefixed_folder(cli_runner: CliRunner, tmp_repo, write_manifest):
    base = Path("pending") / "pfold"
    base.mkdir(parents=True, exist_ok=True)
    (base / "a.txt").write_text("a\n", encoding="utf-8")
    write_manifest(["pfold/"])
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    (base / "a.txt").write_text("aa\n", encoding="utf-8")

    r1 = cli_runner.invoke(app, ["diff", "pfold/"])
    r2 = cli_runner.invoke(app, ["diff", "pending/pfold/"])
    assert r1.exit_code == 0 and r2.exit_code == 0
    assert "📁 pfold/ (folder has changes)" in r1.stdout
    assert "📁 pfold/ (folder has changes)" in r2.stdout


def test_diff_item_windows_style_separators_resolve(cli_runner: CliRunner, tmp_repo, write_manifest):
    (Path("pending") / "nbs").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "nbs" / "h.py").write_text("x\n", encoding="utf-8")
    write_manifest(["nbs/h.py"])  # track
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    (Path("pending") / "nbs" / "h.py").write_text("xx\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["diff", "nbs\\h.py"])  # Windows-style token
    assert res.exit_code == 0
    assert _has_git_diff_markers(res.stdout)


def test_diff_item_unicode_nfc_token_matches(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Use a composed character in filename
    name_composed = "café.txt"
    (Path("pending") / name_composed).write_text("1\n", encoding="utf-8")
    write_manifest([name_composed])
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    (Path("pending") / name_composed).write_text("2\n", encoding="utf-8")

    # Use a decomposed form of café
    name_decomposed = "cafe\u0301.txt"
    res = cli_runner.invoke(app, ["diff", name_decomposed])
    assert res.exit_code == 0
    assert _has_git_diff_markers(res.stdout)


def test_diff_no_arg_missing_preview_shows_no_differences(cli_runner: CliRunner, tmp_repo, write_manifest):
    # preview/ does not exist yet; manifest has tracked entries
    (Path("pending") / "g1.txt").write_text("g\n", encoding="utf-8")
    (Path("pending") / "folder").mkdir(parents=True, exist_ok=True)
    write_manifest(["g1.txt", "folder/"])
    res = cli_runner.invoke(app, ["diff"])  # no-arg
    assert res.exit_code == 0
    out = res.stdout
    assert "📊 Diff: preview vs pending (tracked files only)" in out
    assert "✅ No differences found between tracked files" in out


def test_diff_no_arg_differences_exit_code_zero(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Ensure exit code remains 0 when differences exist
    (Path("pending") / "k.txt").write_text("1\n", encoding="utf-8")
    write_manifest(["k.txt"])  # track file
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0
    (Path("pending") / "k.txt").write_text("2\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["diff"])  # differences present
    assert res.exit_code == 0


