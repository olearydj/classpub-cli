from __future__ import annotations

from pathlib import Path

from classpub_cli.utils import format_ambiguity_list, format_grouped_listing_for_not_found


def test_format_ambiguity_list_truncation():
    candidates = [(Path(f"p{i}"), "file") for i in range(60)]
    lines = format_ambiguity_list(candidates, limit=50)
    assert len(lines) == 51  # 50 items + (+N more)
    assert lines[-1].strip().startswith("(+") and lines[-1].strip().endswith("more)")


def test_format_grouped_listing_for_not_found_truncation(tmp_path, monkeypatch):
    # Create a fake small tree to ensure function runs; then request a tiny limit
    base = tmp_path / "repo"
    (base / "pending").mkdir(parents=True, exist_ok=True)
    for i in range(5):
        (base / "pending" / f"f{i}.txt").write_text("x\n", encoding="utf-8")
    for i in range(5):
        (base / "pending" / f"d{i}").mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(base)
    lines = format_grouped_listing_for_not_found(limit=2)
    # Expect Files: section with (+N more)
    assert any(line.startswith("Files:") for line in lines)
    assert any("(+" in line and "more)" in line for line in lines)

