from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
import os
import unicodedata
from pathlib import Path
from typing import Iterable, Optional, Tuple, List, Sequence

from .paths import PENDING, MANIFEST


logger = logging.getLogger(__name__)


def resolve_repo_root_or_cwd() -> Path:
    # Phase 0: simply return cwd; later phases may enforce presence of pending/
    return Path.cwd()


def check_python_deps() -> list[str]:
    required = [
        "nbformat",
        "nbdime",
        "nbconvert",
        "nbstripout",
    ]
    missing: list[str] = []
    for name in required:
        try:
            __import__(name)
        except Exception:  # pragma: no cover - exact import error type not essential
            missing.append(name)
    return missing


_VER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def git_version_ok(min_ver: Tuple[int, int, int] = (2, 20, 0)) -> tuple[bool, str]:
    exe = shutil.which("git")
    if not exe:
        return False, ""
    try:
        out = subprocess.check_output([exe, "--version"], text=True)
    except Exception:
        return False, ""
    m = _VER_RE.search(out or "")
    if not m:
        return False, out.strip() if out else ""
    ver_tuple = tuple(int(x) for x in m.groups())  # type: ignore[arg-type]
    ok = ver_tuple >= min_ver
    return ok, ".".join(str(x) for x in ver_tuple)


def compute_console_level(verbose_count: int, quiet_count: int, explicit_level: Optional[str]) -> int:
    if explicit_level:
        mapping = {
            "error": logging.ERROR,
            "warning": logging.WARNING,
            "info": logging.INFO,
            "debug": logging.DEBUG,
        }
        return mapping.get(explicit_level.lower(), logging.INFO)
    # Detect environment: default WARNING in production, INFO otherwise
    import os
    env = os.environ.get("CLASSPUB_ENV", "development").lower()
    default_level = logging.WARNING if env in {"prod", "production"} else logging.INFO
    # Start from default and move up/down
    level = default_level
    level -= verbose_count * 10
    level += quiet_count * 10
    # Clamp between DEBUG..ERROR
    level = max(logging.DEBUG, min(logging.ERROR, level))
    return level


# --------------------------
# Phase 1: Manifest + Paths
# --------------------------

# Ignore filters per §8.4
IGNORED_FILES: tuple[str, ...] = (".DS_Store", ".gitignore", ".gitattributes", "RELEASES.txt")
IGNORED_DIRS: tuple[str, ...] = (".ipynb_checkpoints",)


@dataclass(frozen=True)
class Entry:
    raw: str
    rel: Path
    is_dir: bool


def _normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _is_ignored_file(name: str) -> bool:
    return name in IGNORED_FILES


def _is_ignored_dir(name: str) -> bool:
    return name.rstrip("/") in IGNORED_DIRS


def ensure_repo_root_present() -> bool:
    """Return True if repository root looks valid (has pending/)."""
    return PENDING.exists() and PENDING.is_dir()


def read_manifest() -> list[Entry]:
    if not MANIFEST.exists():
        return []
    entries: list[Entry] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        is_dir = s.endswith("/")
        rel = Path(s[:-1] if is_dir else s)
        entries.append(Entry(raw=s, rel=rel, is_dir=is_dir))
    # Deduplicate while preserving order (by exact raw match)
    seen: set[str] = set()
    deduped: list[Entry] = []
    for e in entries:
        if e.raw not in seen:
            seen.add(e.raw)
            deduped.append(e)
    return deduped


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _manifest_lines_from_entries(entries: Sequence[Entry]) -> list[str]:
    return [e.raw for e in entries]


def format_entry_line(rel: Path, is_dir: bool) -> str:
    posix = rel.as_posix()
    return f"{posix}/" if is_dir else posix


def append_entry(rel: Path, is_dir: bool) -> tuple[bool, str]:
    """Append an entry to the manifest if not already present.

    Returns (added, raw_line).
    Creates the manifest file if missing (without header).
    """
    raw = format_entry_line(rel, is_dir)
    entries = read_manifest()
    if any(e.raw == raw for e in entries):
        return False, raw
    entries.append(Entry(raw=raw, rel=rel, is_dir=is_dir))
    text = "\n".join(_manifest_lines_from_entries(entries))
    if text:
        text = text + "\n"
    _atomic_write(MANIFEST, text)
    return True, raw


def remove_entry_by_raw(raw_line: str) -> bool:
    """Remove an exact raw line from the manifest. Returns True if removed.

    If the manifest does not exist, returns False (caller can treat as error).
    """
    if not MANIFEST.exists():
        return False
    entries = [e for e in read_manifest() if e.raw != raw_line]
    # If nothing changed, still rewrite to keep file tidy (but that's optional)
    text = "\n".join(_manifest_lines_from_entries(entries))
    if text:
        text = text + "\n"
    _atomic_write(MANIFEST, text)
    # Determine if removal occurred by comparing sizes
    return any(e.raw == raw_line for e in read_manifest()) is False


class Resolution(Enum):
    FILE = "file"
    DIR = "dir"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


@dataclass(frozen=True)
class Resolved:
    status: Resolution
    rel: Optional[Path] = None
    is_dir: Optional[bool] = None
    candidates: Optional[list[tuple[Path, str]]] = None  # (rel, label "file"|"folder")
    message: str = ""


def normalize_input_token(token: str) -> str:
    s = token.strip()
    s = s.replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    return _normalize_nfc(s)


def _rel_from_absolute_under_pending(abs_path: Path) -> Optional[Path]:
    try:
        abs_path = abs_path.resolve()
        base = PENDING.resolve()
        rel = abs_path.relative_to(base)
        return rel
    except Exception:
        return None


def scan_pending_tree() -> tuple[list[Path], list[Path]]:
    """Return (files, dirs), both relative to PENDING, excluding ignored patterns.
    Directories listed are those that exist under PENDING (not recursive outputs),
    and returned as relative Paths (no trailing slash).
    """
    files: list[Path] = []
    dirs: set[Path] = set()
    if not ensure_repo_root_present():
        return files, list(dirs)
    for root, dirnames, filenames in os.walk(PENDING, followlinks=False):
        # Filter ignored directories in-place to avoid walking them
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
        # Record directories relative to PENDING
        for d in dirnames:
            rel_dir = Path(os.path.relpath(Path(root) / d, PENDING))
            dirs.add(rel_dir)
        for fname in filenames:
            if _is_ignored_file(fname):
                continue
            rel_file = Path(os.path.relpath(Path(root) / fname, PENDING))
            files.append(rel_file)
    # Always include top-level directories under PENDING (even if empty)
    try:
        for p in PENDING.iterdir():
            if p.is_dir() and not _is_ignored_dir(p.name):
                dirs.add(Path(p.name))
    except FileNotFoundError:
        pass
    # Sort deterministically
    files = sorted(files, key=lambda p: p.as_posix())
    dirs_list = sorted(list(dirs), key=lambda p: p.as_posix())
    return files, dirs_list


def resolve_item(token: str) -> Resolved:
    """Resolve a user-provided token to a relative path under PENDING.

    Supports:
      - absolute paths under pending/
      - paths starting with 'pending/' (prefix stripped)
      - relative paths
      - basename search across files and folders when exact match fails
    """
    if not ensure_repo_root_present():
        return Resolved(status=Resolution.ERROR, message="This command must be run from the repository root (missing 'pending/').")

    raw = token
    tok = normalize_input_token(token)

    # Absolute path
    try:
        p = Path(tok)
    except Exception:
        return Resolved(status=Resolution.ERROR, message=f"Invalid path: {raw}")

    if p.is_absolute():
        rel = _rel_from_absolute_under_pending(p)
        if rel is None:
            return Resolved(status=Resolution.ERROR, message=f"Absolute path must be inside pending/: {raw}")
        # Exact check on filesystem
        src = PENDING / rel
        if src.exists():
            return Resolved(status=Resolution.DIR if src.is_dir() else Resolution.FILE, rel=rel, is_dir=src.is_dir())
        # Fallthrough to not-found listing
        return Resolved(status=Resolution.NOT_FOUND)

    # Strip pending/ prefix if present
    if tok.startswith("pending/"):
        tok = tok[len("pending/") :]

    # Trailing slash indicates preference for directory
    prefer_dir = tok.endswith("/")
    tok_no_slash = tok[:-1] if prefer_dir else tok

    # Exact relative path
    exact = (PENDING / tok_no_slash)
    if exact.exists():
        if exact.is_dir():
            return Resolved(status=Resolution.DIR, rel=Path(tok_no_slash), is_dir=True)
        if prefer_dir and exact.is_file():
            # User asked for dir by slash but found a file → ambiguous-like
            # Let basename search handle this for consistent UX
            pass
        else:
            return Resolved(status=Resolution.FILE, rel=Path(tok_no_slash), is_dir=False)

    # Basename search across files and folders
    files, dirs = scan_pending_tree()
    base = _normalize_nfc(Path(tok_no_slash).name)
    cand: list[tuple[Path, str]] = []
    for f in files:
        if _normalize_nfc(f.name) == base:
            cand.append((f, "file"))
    for d in dirs:
        if _normalize_nfc(d.name) == base:
            cand.append((d, "folder"))

    if not cand:
        return Resolved(status=Resolution.NOT_FOUND)
    if len(cand) == 1:
        rel, label = cand[0]
        is_dir = label == "folder"
        return Resolved(status=Resolution.DIR if is_dir else Resolution.FILE, rel=rel, is_dir=is_dir)
    # Multiple candidates → ambiguous
    return Resolved(status=Resolution.AMBIGUOUS, candidates=sorted(cand, key=lambda t: t[0].as_posix()))


def format_grouped_listing_for_not_found(limit: int = 200) -> list[str]:
    files, dirs = scan_pending_tree()
    out: list[str] = []
    if files:
        out.append("Files:")
        display = files[:limit]
        for p in display:
            out.append(f"  {p.as_posix()}")
        if len(files) > limit:
            out.append(f"  (+{len(files) - limit} more)")
    if dirs:
        out.append("Folders:")
        display_d = dirs[:limit]
        for p in display_d:
            out.append(f"  {p.as_posix()}/")
        if len(dirs) > limit:
            out.append(f"  (+{len(dirs) - limit} more)")
    return out


def format_ambiguity_list(candidates: Sequence[tuple[Path, str]], limit: int = 50) -> list[str]:
    out: list[str] = []
    display = list(candidates)[:limit]
    for rel, label in display:
        suffix = "(file)" if label == "file" else "(folder)"
        name = rel.as_posix() + ("/" if label == "folder" else "")
        out.append(f"  {name} {suffix}")
    if len(candidates) > limit:
        out.append(f"  (+{len(candidates) - limit} more)")
    return out

