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
import hashlib
from typing import Iterable, Optional, Tuple, List, Sequence
import nbformat
import json

from .paths import PENDING, MANIFEST
from .config import get_active_config, compile_ignore_matchers


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

# Ignore filters per §8.4 (defaults live here; configurable via config module)
DEFAULT_IGNORED_FILES: tuple[str, ...] = (".DS_Store", ".gitignore", ".gitattributes", "RELEASES.txt")
DEFAULT_IGNORED_DIRS: tuple[str, ...] = (".ipynb_checkpoints",)


@dataclass(frozen=True)
class Entry:
    raw: str
    rel: Path
    is_dir: bool


def _normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _is_ignored_file(name: str) -> bool:
    # Backward-compatible default check; overridden by config-driven helpers in callers
    return name in DEFAULT_IGNORED_FILES


def _is_ignored_dir(name: str) -> bool:
    # Backward-compatible default check; overridden by config-driven helpers in callers
    return name.rstrip("/") in DEFAULT_IGNORED_DIRS


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


# --------------------------
# Phase 2: Hashing & Equality
# --------------------------


def sha256_file(path: Path, chunk_size: int = 8192) -> str:
    """Compute a SHA-256 hex digest of a file by streaming in chunks.

    Uses a fixed chunk size to bound memory usage and is robust for large files.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def files_equal(a: Path, b: Path, chunk_size: int = 8192) -> bool:
    """Return True if two files are byte-identical.

    First compares file sizes; if they match, compares streamed SHA-256 digests.
    """
    sa = a.stat()
    sb = b.stat()
    if sa.st_size != sb.st_size:
        return False
    return sha256_file(a, chunk_size=chunk_size) == sha256_file(b, chunk_size=chunk_size)


# --------------------------
# Notebook-aware comparison
# --------------------------


def _is_notebook(path: Path) -> bool:
    try:
        return path.suffix.lower() == ".ipynb"
    except Exception:
        return False


def _normalized_notebook_text(path: Path) -> str:
    """Return a canonical JSON string of a notebook with outputs/exec-count removed and cell ids dropped.

    Implementation notes:
    - Parse with nbformat, then convert to a plain dict via nbformat.writes()+json.loads
      to avoid re-insertion of ids during serialization.
    - Strip per-cell: outputs=[], execution_count=None, metadata.execution removed, id removed.
    - Return json dumps with sorted keys and compact separators for stable comparison.
    """
    nb = nbformat.read(str(path), as_version=4)
    as_dict = json.loads(nbformat.writes(nb))
    cells = as_dict.get("cells", [])
    for cell in cells:
        try:
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
                md = cell.get("metadata")
                if isinstance(md, dict):
                    md.pop("execution", None)
            # Remove cell id entirely to avoid spurious diffs
            cell.pop("id", None)
        except Exception:
            continue
    as_dict["cells"] = cells
    return json.dumps(as_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def notebook_files_equal(a: Path, b: Path) -> bool:
    """Return True if two notebooks are equal under output/exec-count normalization."""
    try:
        ta = _normalized_notebook_text(a)
        tb = _normalized_notebook_text(b)
        return ta == tb
    except Exception:
        # Fall back to raw file equality on error
        try:
            return files_equal(a, b)
        except Exception:
            return False


def content_equal(a: Path, b: Path) -> bool:
    """Notebook-aware file equality: normalizes .ipynb, byte-compare otherwise."""
    if _is_notebook(a) and _is_notebook(b):
        return notebook_files_equal(a, b)
    return files_equal(a, b)


def _list_rel_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    cfg = get_active_config()
    file_ignored, dir_ignored = compile_ignore_matchers(cfg)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # filter ignored dirs in-place
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirnames[:] = [d for d in dirnames if not dir_ignored(d, f"{rel_dir}/{d}" if rel_dir else d)]
        for fname in filenames:
            rel_posix = (Path(dirpath).relative_to(root) / fname).as_posix()
            if file_ignored(fname, rel_posix):
                continue
            abs_path = Path(dirpath) / fname
            try:
                if abs_path.is_symlink():
                    continue
            except OSError:
                logger.warning("Skipping path due to access issue: %s", abs_path)
                continue
            rel = abs_path.relative_to(root)
            files.append(rel)
    files.sort(key=lambda p: p.as_posix())
    return files


def dir_diff(src: Path, dst: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Compare two directories.

    Returns (added, removed, changed) as lists of relative Paths.
    - added: present only in src
    - removed: present only in dst
    - changed: present in both but with different content
    Applies IGNORED_FILES and IGNORED_DIRS and skips symlinks.
    On comparison errors, paths are treated as changed (conservative).
    """
    src_files = _list_rel_files(src)
    dst_files = _list_rel_files(dst)
    set_s = {p.as_posix() for p in src_files}
    set_d = {p.as_posix() for p in dst_files}
    added = sorted([Path(p) for p in (set_s - set_d)], key=lambda p: p.as_posix())
    removed = sorted([Path(p) for p in (set_d - set_s)], key=lambda p: p.as_posix())
    changed: list[Path] = []
    for common in sorted(set_s & set_d):
        a = src / common
        b = dst / common
        try:
            if not files_equal(a, b):
                changed.append(Path(common))
        except OSError:
            logger.warning("Comparison failed for %s", common)
            changed.append(Path(common))
    return added, removed, changed


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
        # Even if an exact path exists, perform basename disambiguation: if multiple
        # items share this basename across files/folders, treat as ambiguous unless
        # the user explicitly disambiguates via trailing slash or full path.
        files0, dirs0 = scan_pending_tree()
        base0 = _normalize_nfc(Path(tok_no_slash).name)
        cand0: list[tuple[Path, str]] = []
        for f in files0:
            if _normalize_nfc(f.name) == base0:
                cand0.append((f, "file"))
        for d in dirs0:
            if _normalize_nfc(d.name) == base0:
                cand0.append((d, "folder"))
        if len(cand0) > 1:
            return Resolved(status=Resolution.AMBIGUOUS, candidates=sorted(cand0, key=lambda t: t[0].as_posix()))

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

