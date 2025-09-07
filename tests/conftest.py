from __future__ import annotations

from pathlib import Path
import os
import unicodedata

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


# Silence Jupyter deprecation warning about platformdirs by setting the env var at import time
os.environ.setdefault("JUPYTER_PLATFORM_DIRS", "1")


@pytest.fixture
def tmp_repo(tmp_path: Path, monkeypatch):
    repo = tmp_path
    (repo / "pending").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(repo)
    yield repo


@pytest.fixture
def write_manifest(tmp_repo: Path):
    def _write(lines: list[str], mode: str = "w") -> Path:
        manifest = Path("pending") / "RELEASES.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        if mode == "a" and manifest.exists():
            text = manifest.read_text(encoding="utf-8")
        else:
            text = ""
        text += "".join(f"{line}\n" for line in lines)
        manifest.write_text(text, encoding="utf-8")
        return manifest
    return _write


@pytest.fixture
def read_manifest_lines(tmp_repo: Path):
    def _read() -> list[str]:
        m = Path("pending") / "RELEASES.txt"
        if not m.exists():
            return []
        out: list[str] = []
        for line in m.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s)
        return out
    return _read


@pytest.fixture
def fs_tree(tmp_repo: Path):
    def _create(struct: dict[str, Path] | None = None) -> dict[str, Path]:
        base = Path("pending")
        default = {
            "nb_dir": base / "notebooks",
            "data_dir": base / "data",
            "img_dir": base / "images",
            "nb_py": base / "notebooks" / "hello.py",
            "nb_ipynb": base / "notebooks" / "01-intro.ipynb",
            "data_csv": base / "data" / "dataset.csv",
            "img_png": base / "images" / "banner.png",
        }
        items = struct or default
        created: dict[str, Path] = {}
        for key, path in items.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix:
                path.write_text("x\n", encoding="utf-8")
            else:
                path.mkdir(parents=True, exist_ok=True)
            created[key] = path
        return created
    return _create


@pytest.fixture
def make_files(tmp_repo: Path):
    def _make(entries: dict[str, str]) -> list[Path]:
        made: list[Path] = []
        for rel, content in entries.items():
            p = Path("pending") / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            made.append(p)
        return made
    return _make


# Lightweight helpers for tests that need normalization utilities
def posix(path: str) -> str:
    return path.replace("\\", "/")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


