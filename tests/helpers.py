from __future__ import annotations

from pathlib import Path
import unicodedata


def pending_path(*parts: str) -> Path:
    return Path("pending").joinpath(*parts)


def posix(path: str) -> str:
    return path.replace("\\", "/")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


