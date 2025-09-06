from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta

from typer.testing import CliRunner

from classpub_cli.cli import app
import json
import nbformat


def _summary(stdout: str) -> str:
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def test_sync_file_copy_update_unchanged(cli_runner: CliRunner, tmp_repo, write_manifest, make_files):
    write_manifest(["notebooks/hello.py"])
    make_files({"notebooks/hello.py": "print('hi')\n"})

    # first sync: copy → updated=1
    res1 = cli_runner.invoke(app, ["sync", "--yes"])  # avoid removals prompt
    assert res1.exit_code == 0
    assert _summary(res1.stdout) == "✓ Sync complete: 1 updated, 0 removed, 0 unchanged"
    assert (Path("preview") / "notebooks/hello.py").exists()

    # second sync without change → unchanged=1
    res2 = cli_runner.invoke(app, ["sync", "--yes"])
    assert res2.exit_code == 0
    assert _summary(res2.stdout) == "✓ Sync complete: 0 updated, 0 removed, 1 unchanged"

    # modify file → updated=1
    (Path("pending") / "notebooks/hello.py").write_text("print('changed')\n", encoding="utf-8")
    res3 = cli_runner.invoke(app, ["sync", "--yes"])
    assert res3.exit_code == 0
    assert _summary(res3.stdout) == "✓ Sync complete: 1 updated, 0 removed, 0 unchanged"


def test_sync_folder_messages_copied_updated_empty(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create folder with files
    (Path("pending") / "data").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "data" / "a.txt").write_text("a\n", encoding="utf-8")
    (Path("pending") / "data" / "b.txt").write_text("b\n", encoding="utf-8")
    write_manifest(["data/"])

    # First sync → Copied folder data/ (2 files)
    res1 = cli_runner.invoke(app, ["sync", "--yes"])
    assert res1.exit_code == 0
    assert "📁 Copied folder data/ (2 files)" in res1.stdout
    assert _summary(res1.stdout) == "✓ Sync complete: 1 updated, 0 removed, 0 unchanged"

    # Change one file → Updated folder data/ (1 files)
    (Path("pending") / "data" / "a.txt").write_text("aa\n", encoding="utf-8")
    res2 = cli_runner.invoke(app, ["sync", "--yes"])
    assert res2.exit_code == 0
    assert "📁 Updated folder data/ (1 files)" in res2.stdout
    assert _summary(res2.stdout) == "✓ Sync complete: 1 updated, 0 removed, 0 unchanged"

    # Empty folder case
    (Path("pending") / "empty").mkdir(parents=True, exist_ok=True)
    write_manifest(["empty/"], mode="a")
    res3 = cli_runner.invoke(app, ["sync", "--yes"])
    assert res3.exit_code == 0
    assert "📁 Empty folder empty/" in res3.stdout


def test_sync_orphan_prompt_decline_and_accept(cli_runner: CliRunner, tmp_repo, write_manifest):
    # No manifest entries; create orphan in preview
    (Path("preview")).mkdir(exist_ok=True)
    (Path("preview") / "orphan.txt").write_text("x\n", encoding="utf-8")

    # Decline removal
    res1 = cli_runner.invoke(app, ["sync"], input="n\n")
    assert res1.exit_code == 0
    assert "⚠️  These files will be REMOVED from preview (not in manifest):" in res1.stdout
    assert "     - orphan.txt" in res1.stdout
    assert "  Skipped removal" in res1.stdout
    assert (Path("preview") / "orphan.txt").exists()

    # Accept removal
    res2 = cli_runner.invoke(app, ["sync"], input="y\n")
    assert res2.exit_code == 0
    assert (Path("preview") / "orphan.txt").exists() is False


def test_sync_orphan_dry_run_no_delete(cli_runner: CliRunner, tmp_repo):
    (Path("preview")).mkdir(exist_ok=True)
    (Path("preview") / "ghost.txt").write_text("x\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["sync", "--dry-run"])
    assert res.exit_code == 0
    assert "     - ghost.txt" in res.stdout
    # No prompt during dry-run
    assert "Continue with removal?" not in res.stdout
    # File still exists
    assert (Path("preview") / "ghost.txt").exists()
    # Summary reflects would-remove count
    assert _summary(res.stdout) == "✓ Sync complete: 0 updated, 1 removed, 0 unchanged"


def test_sync_yes_auto_removal(cli_runner: CliRunner, tmp_repo):
    (Path("preview")).mkdir(exist_ok=True)
    (Path("preview") / "gone.txt").write_text("x\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["sync", "--yes"])
    assert res.exit_code == 0
    assert (Path("preview") / "gone.txt").exists() is False


def test_sync_preview_symlink_error(cli_runner: CliRunner, tmp_repo):
    # Create preview symlink
    target = Path("_somewhere")
    target.mkdir(exist_ok=True)
    Path("preview").symlink_to(target)
    res = cli_runner.invoke(app, ["sync", "--yes"])
    assert res.exit_code == 1
    assert "preview/ must not be a symlink" in res.stdout


def test_sync_orphans_excludes_tracked_folder_members(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Track data/ folder
    (Path("pending") / "data").mkdir(parents=True, exist_ok=True)
    write_manifest(["data/"])
    # Put a stray file inside preview/data → not considered orphan
    (Path("preview") / "data").mkdir(parents=True, exist_ok=True)
    (Path("preview") / "data" / "extra.txt").write_text("x\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["sync", "--dry-run"])  # dry-run to avoid deletions
    assert res.exit_code == 0
    assert "extra.txt" not in res.stdout


def test_sync_marker_stale_yes_forces_full_resync(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Prepare equal file in preview and pending
    write_manifest(["notebooks/hello.py"])
    (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "notebooks" / "hello.py").write_text("x\n", encoding="utf-8")
    (Path("preview") / "notebooks").mkdir(parents=True, exist_ok=True)
    (Path("preview") / "notebooks" / "hello.py").write_text("x\n", encoding="utf-8")

    # Stale marker
    stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    Path(".sync-in-progress").write_text(f"pid: 0\n" f"time: {stale}\n", encoding="utf-8")

    # With --yes and stale marker → full resync forces update even if equal
    res = cli_runner.invoke(app, ["sync", "--yes"])
    assert res.exit_code == 0
    assert _summary(res.stdout) == "✓ Sync complete: 1 updated, 0 removed, 0 unchanged"


def test_sync_marker_prompt_eof_exit_130(cli_runner: CliRunner, tmp_repo):
    # Create marker to trigger prompt
    stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    Path(".sync-in-progress").write_text(f"pid: 0\n" f"time: {stale}\n", encoding="utf-8")
    res = cli_runner.invoke(app, ["sync"], input="")  # EOF
    assert res.exit_code == 130


def test_sync_then_check_shows_synced_not_touched(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Prepare a single tracked file
    (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "notebooks" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    write_manifest(["notebooks/hello.py"])

    # First sync should copy; subsequent check should show synced, not touched
    r1 = cli_runner.invoke(app, ["sync", "--yes"])
    assert r1.exit_code == 0
    r2 = cli_runner.invoke(app, ["check"])
    assert r2.exit_code == 0
    out = r2.stdout
    assert "✅ notebooks/hello.py" in out
    assert "touched" not in out


def test_sync_multi_entry_counts_first_then_unchanged(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Prepare two files and one folder
    (Path("pending") / "notebooks").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "notebooks" / "a.py").write_text("a\n", encoding="utf-8")
    (Path("pending") / "notebooks" / "b.py").write_text("b\n", encoding="utf-8")
    (Path("pending") / "data").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "data" / "x.txt").write_text("x\n", encoding="utf-8")
    write_manifest(["notebooks/a.py", "notebooks/b.py", "data/"])

    r1 = cli_runner.invoke(app, ["sync", "--yes"])
    assert r1.exit_code == 0
    # 3 manifest entries → all updated
    assert _summary(r1.stdout) == "✓ Sync complete: 3 updated, 0 removed, 0 unchanged"

    r2 = cli_runner.invoke(app, ["sync", "--yes"])
    assert r2.exit_code == 0
    assert _summary(r2.stdout) == "✓ Sync complete: 0 updated, 0 removed, 3 unchanged"


def test_sync_remove_then_yes_removes_file_and_folder(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Track file and folder then initial sync
    (Path("pending") / "notes.md").write_text("n\n", encoding="utf-8")
    (Path("pending") / "imgs").mkdir(parents=True, exist_ok=True)
    (Path("pending") / "imgs" / "one.png").write_text("1\n", encoding="utf-8")
    write_manifest(["notes.md", "imgs/"])
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0

    # Remove from manifest
    from classpub_cli.cli import remove_cmd
    runner = cli_runner
    assert runner.invoke(app, ["remove", "notes.md"]).exit_code == 0
    assert runner.invoke(app, ["remove", "imgs"]).exit_code == 0

    # Orphans should be listed and removed with --yes
    r = runner.invoke(app, ["sync", "--yes"])  # auto-approve removal
    assert r.exit_code == 0
    assert not (Path("preview") / "notes.md").exists()
    assert not (Path("preview") / "imgs").exists()


def test_sync_prunes_empty_nested_dirs(cli_runner: CliRunner, tmp_repo):
    # Manually create nested preview dirs with orphan files
    nested = Path("preview") / "a" / "b" / "c"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "z.txt").write_text("z\n", encoding="utf-8")
    # Empty manifest
    (Path("pending") / "RELEASES.txt").write_text("", encoding="utf-8")
    # Remove orphans
    r = cli_runner.invoke(app, ["sync"], input="y\n")
    assert r.exit_code == 0
    # All empty dirs pruned
    assert (Path("preview") / "a").exists() is False


def test_sync_deep_parent_creation(cli_runner: CliRunner, tmp_repo, write_manifest):
    p = Path("pending") / "deep" / "nested" / "dir" / "file.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("d\n", encoding="utf-8")
    write_manifest(["deep/nested/dir/file.txt"])
    r = cli_runner.invoke(app, ["sync", "--yes"])
    assert r.exit_code == 0
    assert (Path("preview") / "deep" / "nested" / "dir" / "file.txt").exists()


def test_sync_symlink_handling(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Pending symlink inside tracked folder should be skipped (not copied)
    base = Path("pending") / "folder"
    base.mkdir(parents=True, exist_ok=True)
    (base / "real.txt").write_text("r\n", encoding="utf-8")
    # Create a symlink if platform allows
    try:
        (base / "link.lnk").symlink_to("real.txt")
    except Exception:
        pass
    write_manifest(["folder/"])
    r1 = cli_runner.invoke(app, ["sync", "--yes"])
    assert r1.exit_code == 0
    assert (Path("preview") / "folder" / "real.txt").exists()
    # Ensure symlink not present (or ignored)
    assert (Path("preview") / "folder" / "link.lnk").exists() is False


def _write_notebook_with_output(path: Path) -> None:
    nb = nbformat.v4.new_notebook()
    code = "print('hello')\n"
    cell = nbformat.v4.new_code_cell(source=code)
    cell.execution_count = 3
    cell.outputs = [
        nbformat.v4.new_output(output_type="stream", name="stdout", text="hello\n"),
    ]
    nb.cells.append(cell)
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(path))


def test_notebook_outputs_stripped(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange a notebook with execution count and outputs
    nb_src = Path("pending") / "notebooks" / "demo.ipynb"
    _write_notebook_with_output(nb_src)
    write_manifest(["notebooks/demo.ipynb"])  # track file directly

    # Act
    res = cli_runner.invoke(app, ["sync", "--yes"])  # apply strip after copy
    assert res.exit_code == 0

    # Assert preview notebook exists and is stripped
    nb_dst = Path("preview") / "notebooks" / "demo.ipynb"
    assert nb_dst.exists()
    nb = nbformat.read(str(nb_dst), as_version=4)
    code_cells = [c for c in nb.cells if getattr(c, "cell_type", None) == "code"]
    assert code_cells, "expected at least one code cell"
    for c in code_cells:
        assert getattr(c, "outputs", []) == []
        assert getattr(c, "execution_count", None) is None


def test_notebook_strip_skipped_in_dry_run(cli_runner: CliRunner, tmp_repo, write_manifest):
    nb_src = Path("pending") / "notebooks" / "dry.ipynb"
    _write_notebook_with_output(nb_src)
    write_manifest(["notebooks/dry.ipynb"])  # track file directly

    # Dry run should not create or modify preview files
    res = cli_runner.invoke(app, ["sync", "--dry-run"])  # no writes
    assert res.exit_code == 0
    nb_dst = Path("preview") / "notebooks" / "dry.ipynb"
    assert nb_dst.exists() is False


def test_notebook_normalized_equality_prevents_reupdate(cli_runner: CliRunner, tmp_repo, write_manifest):
    # First run: create preview stripped from pending with outputs
    nb_src = Path("pending") / "notebooks" / "norm.ipynb"
    _write_notebook_with_output(nb_src)
    write_manifest(["notebooks/norm.ipynb"])  # tracked file
    r1 = cli_runner.invoke(app, ["sync", "--yes"])  # copies and strips
    assert r1.exit_code == 0

    # Second run: without changing pending, normalized compare should consider equal
    r2 = cli_runner.invoke(app, ["sync", "--yes"])  # should be unchanged
    assert r2.exit_code == 0
    # Summary should show 0 updated, 0 removed, 1 unchanged (one manifest entry)
    lines = [ln for ln in r2.stdout.splitlines() if ln.strip()]
    assert lines and lines[-1].endswith("0 updated, 0 removed, 1 unchanged")


def test_sync_folder_notebooks_stripped_and_idempotent(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange: tracked folder with a notebook that has outputs
    nb_src = Path("pending") / "notebooks" / "f1.ipynb"
    _write_notebook_with_output(nb_src)
    write_manifest(["notebooks/"])

    # First sync: copy and strip
    r1 = cli_runner.invoke(app, ["sync", "--yes"])
    assert r1.exit_code == 0
    nb_dst = Path("preview") / "notebooks" / "f1.ipynb"
    assert nb_dst.exists()
    nb = nbformat.read(str(nb_dst), as_version=4)
    for c in nb.cells:
        if getattr(c, "cell_type", None) == "code":
            assert getattr(c, "outputs", []) == []
            assert getattr(c, "execution_count", None) is None
    # Per-entry counts: updated once
    assert any("✓ Sync complete: 1 updated, 0 removed, 0 unchanged" in ln for ln in r1.stdout.splitlines())

    # Second sync: unchanged per-entry
    r2 = cli_runner.invoke(app, ["sync", "--yes"])
    assert r2.exit_code == 0
    assert any("✓ Sync complete: 0 updated, 0 removed, 1 unchanged" in ln for ln in r2.stdout.splitlines())


def test_sync_no_strip_stdout_noise(cli_runner: CliRunner, tmp_repo, write_manifest):
    nb_src = Path("pending") / "notebooks" / "quiet.ipynb"
    _write_notebook_with_output(nb_src)
    write_manifest(["notebooks/quiet.ipynb"])  # track file directly

    r = cli_runner.invoke(app, ["sync", "--yes"])
    assert r.exit_code == 0
    out_lower = r.stdout.lower()
    # Ensure no explicit stripping messages
    assert "strip" not in out_lower
    assert "outputs" not in out_lower


def test_sync_dry_run_folder_notebooks_no_write(cli_runner: CliRunner, tmp_repo, write_manifest):
    nb_src = Path("pending") / "nbs" / "d1.ipynb"
    _write_notebook_with_output(nb_src)
    write_manifest(["nbs/"])

    r = cli_runner.invoke(app, ["sync", "--dry-run"])  # plan only
    assert r.exit_code == 0
    assert (Path("preview") / "nbs" / "d1.ipynb").exists() is False


def test_symlink_notebook_skipped(cli_runner: CliRunner, tmp_repo, write_manifest):
    base = Path("pending") / "nbdir"
    base.mkdir(parents=True, exist_ok=True)
    real = base / "real.ipynb"
    _write_notebook_with_output(real)
    # Create a symlink to the notebook if possible
    link = base / "link.ipynb"
    try:
        link.symlink_to("real.ipynb")
    except Exception:
        # If symlink creation fails on platform, skip the symlink part
        pass
    write_manifest(["nbdir/"])

    r = cli_runner.invoke(app, ["sync", "--yes"])
    assert r.exit_code == 0
    assert (Path("preview") / "nbdir" / "real.ipynb").exists()
    # Symlink should not be present/copied
    assert (Path("preview") / "nbdir" / "link.ipynb").exists() is False


def test_orphan_ipynb_listed_in_prompt(cli_runner: CliRunner, tmp_repo):
    Path("preview").mkdir(exist_ok=True)
    (Path("preview") / "orphan.ipynb").write_text("{}\n", encoding="utf-8")
    r = cli_runner.invoke(app, ["sync"], input="n\n")
    assert r.exit_code == 0
    assert "⚠️  These files will be REMOVED from preview (not in manifest):" in r.stdout
    assert "     - orphan.ipynb" in r.stdout


def test_sync_prompt_variants(cli_runner: CliRunner, tmp_repo):
    (Path("preview")).mkdir(exist_ok=True)
    (Path("preview") / "o.txt").write_text("x\n", encoding="utf-8")
    # Accept with Y
    r1 = cli_runner.invoke(app, ["sync"], input="Y\n")
    assert r1.exit_code == 0
    # Recreate orphan
    (Path("preview")).mkdir(exist_ok=True)
    (Path("preview") / "o.txt").write_text("x\n", encoding="utf-8")
    # Accept with yes
    r2 = cli_runner.invoke(app, ["sync"], input="yes\n")
    assert r2.exit_code == 0
    # Recreate orphan
    (Path("preview")).mkdir(exist_ok=True)
    (Path("preview") / "o.txt").write_text("x\n", encoding="utf-8")
    # Decline with random answer
    r3 = cli_runner.invoke(app, ["sync"], input="blah\n")
    assert r3.exit_code == 0
    assert (Path("preview") / "o.txt").exists()


