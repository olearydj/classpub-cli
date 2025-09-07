from __future__ import annotations

from pathlib import Path
import os
import sys
import pytest
import base64

import nbformat
from typer.testing import CliRunner

from classpub_cli.cli import app


def _write_nb(path: Path, cells: list[dict] | None = None) -> None:
    nb = nbformat.v4.new_notebook()
    nb["cells"] = cells or []
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(path))


def test_to_md_converts_from_pending_default_strip(cli_runner: CliRunner, tmp_repo, write_manifest):
    nbp = Path("pending") / "notebooks" / "demo.ipynb"
    _write_nb(nbp, cells=[nbformat.v4.new_markdown_cell("Hello World")])
    write_manifest(["notebooks/demo.ipynb"])  # tracked

    res = cli_runner.invoke(app, ["to-md"])  # defaults: source=pending, outputs=strip
    assert res.exit_code == 0
    out_md = Path("pending") / "md" / "notebooks" / "demo.md"
    assert out_md.exists()
    assert "Hello World" in out_md.read_text(encoding="utf-8")
    assert "✓ Converted:" in res.stdout


def test_to_md_outputs_keep_vs_strip_text_output(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Notebook with a code cell that already contains output text
    code_cell = nbformat.v4.new_code_cell("x=1")
    code_cell["outputs"] = [
        nbformat.v4.new_output(output_type="stream", name="stdout", text="OUTPUT-XYZ\n")
    ]
    nbp = Path("pending") / "notebooks" / "out.ipynb"
    _write_nb(nbp, cells=[code_cell])
    write_manifest(["notebooks/out.ipynb"])  # tracked

    # keep → markdown should contain the output text marker
    res_keep = cli_runner.invoke(app, ["to-md", "--outputs", "keep"])  # default source=pending
    assert res_keep.exit_code == 0
    md_path = Path("pending") / "md" / "notebooks" / "out.md"
    assert md_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "OUTPUT-XYZ" in md_text

    # strip → regenerate markdown without outputs content
    res_strip = cli_runner.invoke(app, ["to-md", "--outputs", "strip"])  # default source=pending
    assert res_strip.exit_code == 0
    md_text2 = md_path.read_text(encoding="utf-8")
    # Heuristic: when stripped, the literal output should be absent
    assert "OUTPUT-XYZ" not in md_text2


def test_to_md_source_preview_used_when_requested(cli_runner: CliRunner, tmp_repo, write_manifest):
    rel = Path("notebooks") / "which.ipynb"
    # pending contains PENDING marker
    _write_nb(Path("pending") / rel, cells=[nbformat.v4.new_markdown_cell("PENDING")])
    # preview contains PREVIEW marker
    prev = Path("preview") / rel
    _write_nb(prev, cells=[nbformat.v4.new_markdown_cell("PREVIEW")])
    write_manifest([rel.as_posix()])

    res = cli_runner.invoke(app, ["to-md", "--source", "preview", "--outputs", "keep"])
    assert res.exit_code == 0
    md_path = Path("pending") / "md" / rel.with_suffix(".md")
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "PREVIEW" in text and "PENDING" not in text


def test_to_md_source_preview_missing_skips_with_zero_converted(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Manifest refers to a notebook that exists in pending but not preview
    rel = Path("notebooks") / "missing.ipynb"
    _write_nb(Path("pending") / rel, cells=[nbformat.v4.new_markdown_cell("X")])
    write_manifest([rel.as_posix()])

    res = cli_runner.invoke(app, ["to-md", "--source", "preview"])  # missing preview copy
    assert res.exit_code == 0
    # No md generated
    assert not (Path("pending") / "md" / rel.with_suffix(".md")).exists()
    # Summary still printed
    assert "✓ Converted: 0 notebooks" in res.stdout


def test_to_md_writes_resources_for_image_output(cli_runner: CliRunner, tmp_repo, write_manifest):
    # 1x1 transparent PNG
    img_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAJpD0KQAAAAASUVORK5CYII="
    )
    code_cell = nbformat.v4.new_code_cell("")
    code_cell["outputs"] = [
        nbformat.v4.new_output(output_type="display_data", data={"image/png": img_b64}, metadata={})
    ]
    rel = Path("notebooks") / "img.ipynb"
    _write_nb(Path("pending") / rel, cells=[code_cell])
    write_manifest([rel.as_posix()])

    res = cli_runner.invoke(app, ["to-md", "--outputs", "keep"])  # keep outputs so resources are emitted
    assert res.exit_code == 0
    res_dir = Path("pending") / "md" / "notebooks" / "img_files"
    assert res_dir.exists()
    # Directory should contain at least one file
    assert any(p.is_file() for p in res_dir.iterdir())


def test_to_md_ignores_ipynb_checkpoints(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create a checkpoints notebook and a real one under the tracked folder
    chk = Path("pending") / "nbs" / ".ipynb_checkpoints" / "tmp.ipynb"
    real = Path("pending") / "nbs" / "real.ipynb"
    _write_nb(chk, cells=[nbformat.v4.new_markdown_cell("CHK")])
    _write_nb(real, cells=[nbformat.v4.new_markdown_cell("REAL")])
    write_manifest(["nbs/"])

    res = cli_runner.invoke(app, ["to-md"])  # default pending/ source
    assert res.exit_code == 0
    # Only real.md should exist
    assert (Path("pending") / "md" / "nbs" / "real.md").exists()
    assert not (Path("pending") / "md" / "nbs" / ".ipynb_checkpoints" / "tmp.md").exists()


def test_to_md_preserves_relative_structure(cli_runner: CliRunner, tmp_repo, write_manifest):
    rel = Path("course") / "sec1" / "demo.ipynb"
    _write_nb(Path("pending") / rel, cells=[nbformat.v4.new_markdown_cell("S")])
    write_manifest(["course/"])

    res = cli_runner.invoke(app, ["to-md"])  # default pending
    assert res.exit_code == 0
    assert (Path("pending") / "md" / "course" / "sec1" / "demo.md").exists()


def test_to_md_execute_missing_ipykernel_errors_cleanly(cli_runner: CliRunner, tmp_repo, write_manifest, monkeypatch):
    rel = Path("notebooks") / "exec.ipynb"
    _write_nb(Path("pending") / rel, cells=[nbformat.v4.new_code_cell("x=1")])
    write_manifest([rel.as_posix()])

    # Force the execution helper to raise the same error we emit when ipykernel is missing
    monkeypatch.setattr("classpub_cli.convert._execute_in_venv", lambda nb, cwd: (_ for _ in ()).throw(RuntimeError("ipykernel is required for --execute; install with: uv pip install ipykernel")))

    res = cli_runner.invoke(app, ["to-md", "--execute"])  # triggers the error path
    assert res.exit_code == 1
    assert "ipykernel is required for --execute" in res.stdout


def test_to_md_strip_does_not_modify_source_notebook(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Arrange a notebook with an output in pending
    code_cell = nbformat.v4.new_code_cell("x=1")
    code_cell["outputs"] = [nbformat.v4.new_output(output_type="stream", name="stdout", text="ORIG_OUT\n")]
    rel = Path("notebooks") / "keep_source.ipynb"
    _write_nb(Path("pending") / rel, cells=[code_cell])
    write_manifest([rel.as_posix()])

    # Act: convert with strip; source should not change
    res = cli_runner.invoke(app, ["to-md", "--outputs", "strip"])  # default source=pending
    assert res.exit_code == 0

    # Assert: pending notebook still has outputs
    nb = nbformat.read(str(Path("pending") / rel), as_version=4)
    outs = [out for cell in nb.cells if cell.get("cell_type") == "code" for out in cell.get("outputs", [])]
    assert any(getattr(o, "output_type", getattr(o, "get", lambda *_: None)("output_type")) == "stream" or (isinstance(o, dict) and o.get("output_type") == "stream") for o in outs)


def test_to_md_preview_keep_uses_stripped_preview_outputs(cli_runner: CliRunner, tmp_repo, write_manifest):
    # pending has outputs; preview will be stripped by sync
    code_cell = nbformat.v4.new_code_cell("x=1")
    code_cell["outputs"] = [nbformat.v4.new_output(output_type="stream", name="stdout", text="OUTPUT-XYZ\n")]
    rel = Path("nbs") / "striptest.ipynb"
    _write_nb(Path("pending") / rel, cells=[code_cell])
    write_manifest([rel.as_posix()])
    # Create stripped preview via sync
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0

    # Keep outputs from preview (which are stripped) → md should not contain OUTPUT-XYZ
    res = cli_runner.invoke(app, ["to-md", "--source", "preview", "--outputs", "keep"])
    assert res.exit_code == 0
    md_path = Path("pending") / "md" / rel.with_suffix(".md")
    assert md_path.exists()
    assert "OUTPUT-XYZ" not in md_path.read_text(encoding="utf-8")


def test_to_md_existing_resources_dir_preserved(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Notebook that produces an image resource
    img_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAJpD0KQAAAAASUVORK5CYII="
    cell = nbformat.v4.new_code_cell("")
    cell["outputs"] = [nbformat.v4.new_output(output_type="display_data", data={"image/png": img_b64}, metadata={})]
    rel = Path("imgcase") / "res.ipynb"
    _write_nb(Path("pending") / rel, cells=[cell])
    write_manifest([rel.as_posix()])

    # Pre-create resources dir with an extra file
    res_dir = Path("pending") / "md" / rel.parent / (rel.stem + "_files")
    res_dir.mkdir(parents=True, exist_ok=True)
    extra = res_dir / "extra.txt"
    extra.write_text("keep me\n", encoding="utf-8")

    res = cli_runner.invoke(app, ["to-md", "--outputs", "keep"])  # generate resources
    assert res.exit_code == 0
    # Extra file remains and at least one generated file exists
    assert extra.exists()
    assert any(p.name != "extra.txt" for p in res_dir.iterdir())


def test_to_md_multiple_runs_idempotent(cli_runner: CliRunner, tmp_repo, write_manifest):
    rel = Path("deep") / "idem.ipynb"
    _write_nb(Path("pending") / rel, cells=[nbformat.v4.new_markdown_cell("A")])
    write_manifest([rel.as_posix()])

    r1 = cli_runner.invoke(app, ["to-md"])  # first run
    assert r1.exit_code == 0
    md = Path("pending") / "md" / rel.with_suffix(".md")
    text1 = md.read_text(encoding="utf-8")

    r2 = cli_runner.invoke(app, ["to-md"])  # second run
    assert r2.exit_code == 0
    text2 = md.read_text(encoding="utf-8")
    assert text1 == text2


def test_to_md_unicode_and_spaces_paths(cli_runner: CliRunner, tmp_repo, write_manifest):
    rel = Path("course") / "sec 1" / "café test.ipynb"
    _write_nb(Path("pending") / rel, cells=[nbformat.v4.new_markdown_cell("Üñîçødë")])
    write_manifest(["course/"])

    res = cli_runner.invoke(app, ["to-md"])  # default pending
    assert res.exit_code == 0
    md = Path("pending") / "md" / rel.with_suffix(".md")
    assert md.exists()
    assert "Üñîçødë" in md.read_text(encoding="utf-8")


def test_to_md_invalid_flag_values(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Minimal manifest
    _write_nb(Path("pending") / "a.ipynb", cells=[nbformat.v4.new_markdown_cell("x")])
    write_manifest(["a.ipynb"]) 

    r1 = cli_runner.invoke(app, ["to-md", "--source", "invalid"])  # bad source
    assert r1.exit_code == 1
    assert "Invalid --source" in r1.stdout

    r2 = cli_runner.invoke(app, ["to-md", "--outputs", "wrong"])  # bad outputs
    assert r2.exit_code == 1
    assert "Invalid --outputs" in r2.stdout


def test_to_md_folder_manifest_only_ipynb_converted(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Create a mixed folder
    base = Path("pending") / "mix"
    (base / "mix.py").parent.mkdir(parents=True, exist_ok=True)
    (base / "mix.py").write_text("print(1)\n", encoding="utf-8")
    _write_nb(base / "n1.ipynb", cells=[nbformat.v4.new_markdown_cell("N1")])
    _write_nb(base / "n2.ipynb", cells=[nbformat.v4.new_markdown_cell("N2")])
    write_manifest(["mix/"])

    res = cli_runner.invoke(app, ["to-md"])  # default pending
    assert res.exit_code == 0
    # Only ipynb have md outputs
    assert (Path("pending") / "md" / "mix" / "n1.md").exists()
    assert (Path("pending") / "md" / "mix" / "n2.md").exists()
    assert not (Path("pending") / "md" / "mix" / "mix.py").exists()


def test_to_md_newline_normalization(cli_runner: CliRunner, tmp_repo, write_manifest):
    rel = Path("simple") / "line.ipynb"
    _write_nb(Path("pending") / rel, cells=[nbformat.v4.new_markdown_cell("L1")])
    write_manifest([rel.as_posix()])

    res = cli_runner.invoke(app, ["to-md"])  # default
    assert res.exit_code == 0
    md = Path("pending") / "md" / rel.with_suffix(".md")
    assert md.exists()
    assert md.read_text(encoding="utf-8").endswith("\n")


def test_to_md_integration_pending_keep_then_preview_keep_overwrites_with_stripped(cli_runner: CliRunner, tmp_repo, write_manifest):
    # pending with outputs
    cell = nbformat.v4.new_code_cell("x=1")
    cell["outputs"] = [nbformat.v4.new_output(output_type="stream", name="stdout", text="OUTPUT-XYZ\n")]
    rel = Path("dual") / "case.ipynb"
    _write_nb(Path("pending") / rel, cells=[cell])
    write_manifest([rel.as_posix()])
    # Create stripped preview via sync
    assert cli_runner.invoke(app, ["sync", "--yes"]).exit_code == 0

    md = Path("pending") / "md" / rel.with_suffix(".md")

    # First: from pending keep → md contains outputs
    r1 = cli_runner.invoke(app, ["to-md", "--source", "pending", "--outputs", "keep"])
    assert r1.exit_code == 0
    assert "OUTPUT-XYZ" in md.read_text(encoding="utf-8")

    # Second: from preview keep (stripped) → md overwritten without outputs
    r2 = cli_runner.invoke(app, ["to-md", "--source", "preview", "--outputs", "keep"])
    assert r2.exit_code == 0
    assert "OUTPUT-XYZ" not in md.read_text(encoding="utf-8")


def test_to_md_execute_uses_current_python(cli_runner: CliRunner, tmp_repo, write_manifest):
    # Skip if ipykernel is not installed in this environment
    pytest.importorskip("ipykernel")

    rel = Path("execsrc") / "whoami.ipynb"
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell("import sys; print(sys.executable)")]
    p = Path("pending") / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(p))
    write_manifest([rel.as_posix()])

    res = cli_runner.invoke(app, ["to-md", "--execute", "--outputs", "keep"])  # should execute in current venv
    assert res.exit_code == 0
    md_path = Path("pending") / "md" / rel.with_suffix(".md")
    assert md_path.exists()

    md_text = md_path.read_text(encoding="utf-8")
    exe_name = os.path.basename(sys.executable)
    # The Markdown should contain the interpreter path or at least the basename
    assert exe_name in md_text or sys.executable in md_text


def test_to_md_stale_markdown_not_removed_when_notebook_removed(cli_runner: CliRunner, tmp_repo, write_manifest):
    base = Path("pending") / "nbs"
    (base).mkdir(parents=True, exist_ok=True)
    # Two notebooks under a tracked folder
    a = base / "a.ipynb"
    b = base / "b.ipynb"
    _write_nb(a, cells=[nbformat.v4.new_markdown_cell("A")])
    _write_nb(b, cells=[nbformat.v4.new_markdown_cell("B")])
    write_manifest(["nbs/"])

    # Initial conversion creates both md files
    r1 = cli_runner.invoke(app, ["to-md"])  # default pending
    assert r1.exit_code == 0
    a_md = Path("pending") / "md" / "nbs" / "a.md"
    b_md = Path("pending") / "md" / "nbs" / "b.md"
    assert a_md.exists() and b_md.exists()

    # Remove one notebook from pending
    a.unlink()

    # Re-run conversion; stale a.md should remain (non-deletion policy)
    r2 = cli_runner.invoke(app, ["to-md"])  # default pending
    assert r2.exit_code == 0
    assert a_md.exists()  # stale md not deleted
    assert b_md.exists()


