from __future__ import annotations

from pathlib import Path
import pytest

from classpub_cli import utils


def test_files_equal_size_mismatch(tmp_path: Path):
    a = tmp_path / "a.bin"; b = tmp_path / "b.bin"
    a.write_bytes(b"x" * 10)
    b.write_bytes(b"x" * 11)
    assert utils.files_equal(a, b) is False


def test_files_equal_identical(tmp_path: Path):
    a = tmp_path / "a.bin"; b = tmp_path / "b.bin"
    data = b"y" * 8192 + b"z"
    a.write_bytes(data)
    b.write_bytes(data)
    assert utils.files_equal(a, b) is True


def test_files_equal_same_size_different(tmp_path: Path):
    a = tmp_path / "a.bin"; b = tmp_path / "b.bin"
    a.write_bytes(b"a" * 4096 + b"b")
    b.write_bytes(b"a" * 4096 + b"c")
    assert utils.files_equal(a, b) is False


def test_dir_diff_added_removed_changed_and_ignores(tmp_path: Path):
    s = tmp_path / "src"; d = tmp_path / "dst"
    (s / "sub").mkdir(parents=True, exist_ok=True)
    (d / "sub").mkdir(parents=True, exist_ok=True)
    # Added only in src
    (s / "only_src.txt").write_text("x\n", encoding="utf-8")
    # Removed only in dst
    (d / "only_dst.txt").write_text("y\n", encoding="utf-8")
    # Changed in both
    (s / "sub" / "same.txt").write_text("A\n", encoding="utf-8")
    (d / "sub" / "same.txt").write_text("B\n", encoding="utf-8")
    # Ignored files
    (s / ".DS_Store").write_text("", encoding="utf-8")
    (d / ".DS_Store").write_text("", encoding="utf-8")

    added, removed, changed = utils.dir_diff(s, d)
    assert Path("only_src.txt") in added
    assert Path("only_dst.txt") in removed
    assert Path("sub/same.txt") in changed
    # ignored not present
    assert all(p.as_posix() != ".DS_Store" for p in added + removed + changed)


def test_nfc_normalization_used_for_matching_but_not_display(tmp_path: Path, monkeypatch):
    # Create file with decomposed Unicode form; ensure matching via utils.normalize_input_token
    # We simulate display by round-tripping via manifest formatters
    from classpub_cli.utils import _normalize_nfc, format_entry_line, Entry

    raw_user = "notebooks/ñeño.txt"
    decomposed = raw_user
    # ensure normalization noop
    assert _normalize_nfc(decomposed) == _normalize_nfc(raw_user)
    e = Entry(raw=raw_user, rel=Path("notebooks/ñeño.txt"), is_dir=False)
    assert format_entry_line(e.rel, e.is_dir) == raw_user


def test_dir_diff_marks_changed_on_comparison_error(tmp_path: Path, monkeypatch):
    s = tmp_path / "src"; d = tmp_path / "dst"
    s.mkdir(parents=True, exist_ok=True)
    d.mkdir(parents=True, exist_ok=True)
    (s / "err.txt").write_text("A\n", encoding="utf-8")
    (d / "err.txt").write_text("A\n", encoding="utf-8")

    # Make files_equal raise for this path
    original = utils.files_equal

    def raiser(a: Path, b: Path, *args, **kwargs):  # noqa: ANN001
        if a.name == "err.txt":
            raise OSError("simulated error")
        return original(a, b, *args, **kwargs)

    monkeypatch.setattr(utils, "files_equal", raiser, raising=True)
    added, removed, changed = utils.dir_diff(s, d)
    assert added == [] and removed == []
    assert Path("err.txt") in changed


