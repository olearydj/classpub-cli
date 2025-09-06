from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .paths import PENDING, PREVIEW
from .utils import Entry, IGNORED_DIRS, IGNORED_FILES, read_manifest, ensure_repo_root_present, files_equal


logger = logging.getLogger(__name__)


class ItemStatus(str, Enum):
    SYNCED = "synced"
    MODIFIED = "modified"
    TOUCHED = "touched"
    STAGED = "staged"
    UNTRACKED = "untracked"
    REMOVED = "removed"


@dataclass(frozen=True)
class StatusLine:
    rel_path: str
    status: ItemStatus
    is_folder: bool = False
    note: Optional[str] = None  # e.g., "missing_from_pending"


@dataclass(frozen=True)
class StatusCounters:
    synced: int = 0
    modified: int = 0
    touched: int = 0
    staged: int = 0
    untracked: int = 0
    removed: int = 0


@dataclass(frozen=True)
class StatusReport:
    lines: list[StatusLine]
    counters: StatusCounters


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except Exception:
        return False


def _iter_rel_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # filter ignored dirs
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for fname in filenames:
            if fname in IGNORED_FILES:
                continue
            abs_path = Path(dirpath) / fname
            try:
                if abs_path.is_symlink():
                    continue
            except OSError:
                # Permission or race; skip conservatively
                logger.warning("Skipping path due to access issue: %s", abs_path)
                continue
            rel = abs_path.relative_to(root)
            files.append(rel)
    files.sort(key=lambda p: p.as_posix())
    return files


def _format_folder_rel(rel: Path) -> str:
    s = rel.as_posix()
    return s + "/" if not s.endswith("/") else s


def _classify_folder(pending_dir: Path, preview_dir: Path) -> ItemStatus:
    """Return folder status from high-level presence and simple content equality heuristic.

    Detailed per-file change lists are not required for Phase 2; we only need to
    decide synced vs modified vs staged.
    """
    if not preview_dir.exists():
        return ItemStatus.STAGED
    if not pending_dir.exists():
        # Handled by caller as a special note; treat as modified for counters
        return ItemStatus.MODIFIED

    # Compare directory contents by walking both and comparing sets + file equality
    pend_files = _iter_rel_files(pending_dir)
    prev_files = _iter_rel_files(preview_dir)
    set_p = {p.as_posix() for p in pend_files}
    set_q = {p.as_posix() for p in prev_files}
    if set_p != set_q:
        return ItemStatus.MODIFIED
    # Same file set; verify contents
    for rel_str in set_p:
        src = pending_dir / rel_str
        dst = preview_dir / rel_str
        try:
            if not files_equal(src, dst):
                return ItemStatus.MODIFIED
        except OSError:
            logger.warning("Content compare failed for %s", rel_str)
            return ItemStatus.MODIFIED
    return ItemStatus.SYNCED


def compute_status() -> StatusReport:
    """Compute status report based on current PENDING/PREVIEW and manifest.

    - Per-file lines for files tracked directly (not under tracked folders)
    - One line per tracked folder (manifest order)
    - Orphan files under preview (not tracked directly and not under tracked folders)
    """
    lines: list[StatusLine] = []
    counters = StatusCounters()

    if not ensure_repo_root_present():
        # No pending/; return empty report (caller will emit error message)
        return StatusReport(lines=lines, counters=counters)

    entries: list[Entry] = read_manifest()
    tracked_file_set = {e.rel.as_posix() for e in entries if not e.is_dir}
    tracked_folders: list[Path] = [e.rel for e in entries if e.is_dir]

    # Per-file statuses
    pending_files = _iter_rel_files(PENDING)
    for rel in pending_files:
        posix = rel.as_posix()
        tracked_direct = posix in tracked_file_set
        tracked_by_folder = any(_is_relative_to(rel, folder) for folder in tracked_folders)
        if tracked_direct and not tracked_by_folder:
            src = PENDING / rel
            dst = PREVIEW / rel
            if not dst.exists():
                lines.append(StatusLine(rel_path=posix, status=ItemStatus.STAGED, is_folder=False))
                counters = dataclass_replace(counters, staged=counters.staged + 1)
            else:
                try:
                    if files_equal(src, dst):
                        # touched if newer mtime on src
                        try:
                            if src.stat().st_mtime_ns > dst.stat().st_mtime_ns:
                                lines.append(StatusLine(rel_path=posix, status=ItemStatus.TOUCHED, is_folder=False))
                                counters = dataclass_replace(counters, touched=counters.touched + 1)
                            else:
                                lines.append(StatusLine(rel_path=posix, status=ItemStatus.SYNCED, is_folder=False))
                                counters = dataclass_replace(counters, synced=counters.synced + 1)
                        except OSError:
                            # If stat fails, fall back to synced when content equal
                            lines.append(StatusLine(rel_path=posix, status=ItemStatus.SYNCED, is_folder=False))
                            counters = dataclass_replace(counters, synced=counters.synced + 1)
                    else:
                        lines.append(StatusLine(rel_path=posix, status=ItemStatus.MODIFIED, is_folder=False))
                        counters = dataclass_replace(counters, modified=counters.modified + 1)
                except OSError:
                    # Conservative: consider modified on error
                    lines.append(StatusLine(rel_path=posix, status=ItemStatus.MODIFIED, is_folder=False))
                    counters = dataclass_replace(counters, modified=counters.modified + 1)
        elif not tracked_direct and not tracked_by_folder:
            lines.append(StatusLine(rel_path=posix, status=ItemStatus.UNTRACKED, is_folder=False))
            counters = dataclass_replace(counters, untracked=counters.untracked + 1)
        # else: inside tracked folder → no per-file line

    # Folder statuses (manifest order)
    for folder in tracked_folders:
        src_dir = PENDING / folder
        dst_dir = PREVIEW / folder
        if not src_dir.exists():
            # Missing from pending (warning), counts as modified
            lines.append(
                StatusLine(rel_path=_format_folder_rel(folder), status=ItemStatus.MODIFIED, is_folder=True, note="missing_from_pending")
            )
            counters = dataclass_replace(counters, modified=counters.modified + 1)
            continue
        status = _classify_folder(src_dir, dst_dir)
        lines.append(StatusLine(rel_path=_format_folder_rel(folder), status=status, is_folder=True))
        if status is ItemStatus.SYNCED:
            counters = dataclass_replace(counters, synced=counters.synced + 1)
        elif status is ItemStatus.MODIFIED:
            counters = dataclass_replace(counters, modified=counters.modified + 1)
        elif status is ItemStatus.STAGED:
            counters = dataclass_replace(counters, staged=counters.staged + 1)

    # Orphans under preview
    preview_files = _iter_rel_files(PREVIEW)
    preview_set = {p.as_posix() for p in preview_files}
    tracked_by_folder_files: set[str] = set()
    for rel in preview_files:
        if any(_is_relative_to(rel, folder) for folder in tracked_folders):
            tracked_by_folder_files.add(rel.as_posix())
    tracked_direct_in_preview = {p for p in preview_set if p in tracked_file_set}
    orphans = sorted(list(preview_set - tracked_by_folder_files - tracked_direct_in_preview))
    for posix in orphans:
        lines.append(StatusLine(rel_path=posix, status=ItemStatus.REMOVED, is_folder=False))
        counters = dataclass_replace(counters, removed=counters.removed + 1)

    # Ensure deterministic order: sort by path within each status group
    status_order = {
        ItemStatus.MODIFIED: 0,
        ItemStatus.TOUCHED: 1,
        ItemStatus.STAGED: 2,
        ItemStatus.UNTRACKED: 3,
        ItemStatus.REMOVED: 4,
        ItemStatus.SYNCED: 5,
    }
    lines.sort(key=lambda ln: (status_order.get(ln.status, 99), ln.rel_path))

    return StatusReport(lines=lines, counters=counters)


def dataclass_replace(counters: StatusCounters, **kwargs: int) -> StatusCounters:
    # Lightweight helper to keep counters immutable-like
    return StatusCounters(
        synced=kwargs.get("synced", counters.synced),
        modified=kwargs.get("modified", counters.modified),
        touched=kwargs.get("touched", counters.touched),
        staged=kwargs.get("staged", counters.staged),
        untracked=kwargs.get("untracked", counters.untracked),
        removed=kwargs.get("removed", counters.removed),
    )


