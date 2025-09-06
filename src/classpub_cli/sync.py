from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
import socket
import time
from pathlib import Path
from typing import Callable, Iterable, List, Tuple
import nbformat

from .paths import PENDING, PREVIEW
from .utils import Entry, read_manifest, files_equal, IGNORED_DIRS, IGNORED_FILES, _atomic_write, content_equal


logger = logging.getLogger(__name__)


@dataclass
class FileOp:
    src: Path
    dst: Path
    kind: str  # "copy" | "update"


@dataclass
class SyncCounts:
    updated: int = 0  # per-manifest-entry updated count
    removed: int = 0  # number of files removed from preview
    unchanged: int = 0  # per-manifest-entry unchanged count


def _ensure_repo_root() -> bool:
    return PENDING.exists() and PENDING.is_dir()


def _is_symlink(p: Path) -> bool:
    try:
        return p.is_symlink()
    except OSError:
        return False


def _iter_rel_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for fname in filenames:
            if fname in IGNORED_FILES:
                continue
            abs_path = Path(dirpath) / fname
            if _is_symlink(abs_path):
                continue
            files.append(abs_path.relative_to(root))
    files.sort(key=lambda p: p.as_posix())
    return files


def _atomic_copy(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # copy in chunks to temp then replace to keep atomicity
    with src.open("rb") as fsrc, tmp.open("wb") as fdst:
        while True:
            chunk = fsrc.read(1024 * 1024)
            if not chunk:
                break
            fdst.write(chunk)
    os.replace(tmp, dst)
    try:
        st = src.stat()
        # Preserve nanosecond precision to avoid false "touched" status
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    except Exception:
        pass


def build_sync_plan(entries: list[Entry], *, force_full_resync: bool = False) -> tuple[list[FileOp], dict[str, bool]]:
    """Return (file_ops, per_entry_updated_map).

    per_entry_updated_map maps entry.raw -> True if any file needs copy/update, else False.
    """
    ops: list[FileOp] = []
    per_entry_updated: dict[str, bool] = {}

    for e in entries:
        per_entry_updated[e.raw] = False
        if e.is_dir:
            src_dir = PENDING / e.rel
            if not src_dir.exists():
                # Missing from pending → nothing to copy (treated as unchanged here)
                continue
            # Walk pending dir and compute ops
            for rel in _iter_rel_files(src_dir):
                src = src_dir / rel
                dst = PREVIEW / e.rel / rel
                if not dst.exists():
                    ops.append(FileOp(src=src, dst=dst, kind="copy"))
                    per_entry_updated[e.raw] = True
                else:
                    try:
                        if force_full_resync or (not content_equal(src, dst)):
                            ops.append(FileOp(src=src, dst=dst, kind="update"))
                            per_entry_updated[e.raw] = True
                    except OSError:
                        logger.warning("Comparison failed for %s", rel)
                        ops.append(FileOp(src=src, dst=dst, kind="update"))
                        per_entry_updated[e.raw] = True
        else:
            src = PENDING / e.rel
            dst = PREVIEW / e.rel
            if not src.exists():
                continue
            if not dst.exists():
                ops.append(FileOp(src=src, dst=dst, kind="copy"))
                per_entry_updated[e.raw] = True
            else:
                try:
                    if force_full_resync or (not content_equal(src, dst)):
                        ops.append(FileOp(src=src, dst=dst, kind="update"))
                        per_entry_updated[e.raw] = True
                except OSError:
                    logger.warning("Comparison failed for %s", e.rel.as_posix())
                    ops.append(FileOp(src=src, dst=dst, kind="update"))
                    per_entry_updated[e.raw] = True

    return ops, per_entry_updated


def _apply_file_ops(ops: list[FileOp], dry_run: bool) -> None:
    for op in ops:
        if dry_run:
            continue
        _atomic_copy(op.src, op.dst)


def _list_orphans(entries: list[Entry]) -> list[Path]:
    """Return orphan files under PREVIEW (relative Paths).

    Orphans are files not tracked directly and not under any tracked folder.
    """
    preview_files = _iter_rel_files(PREVIEW)
    tracked_files = {e.rel.as_posix() for e in entries if not e.is_dir}
    tracked_dirs = [e.rel for e in entries if e.is_dir]

    def _in_any_tracked_dir(rel: Path) -> bool:
        for d in tracked_dirs:
            try:
                rel.relative_to(d)
                return True
            except Exception:
                continue
        return False

    orphans: list[Path] = []
    for rel in preview_files:
        posix = rel.as_posix()
        if posix in tracked_files:
            continue
        if _in_any_tracked_dir(rel):
            continue
        orphans.append(rel)
    return sorted(orphans, key=lambda p: p.as_posix())


class PromptAborted(Exception):
    pass


def _prompt_yes() -> bool:
    try:
        # Print prompt to stdout per spec
        sys.stdout.write("  Continue with removal? [y/N] ")
        sys.stdout.flush()
        raw = sys.stdin.readline()
        if raw == "":
            # EOF
            raise PromptAborted()
        ans = raw.strip()
        return ans in {"y", "Y", "yes"}
    except KeyboardInterrupt:
        raise
    except Exception:
        return False


def _remove_files(paths: list[Path], dry_run: bool) -> int:
    count = 0
    for rel in paths:
        abs_path = PREVIEW / rel
        try:
            if _is_symlink(abs_path):
                continue
            if dry_run:
                count += 1
                continue
            if abs_path.exists() and abs_path.is_file():
                abs_path.unlink()
                count += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error("Failed to remove %s: %s", abs_path, e)
            raise
    return count


def _prune_empty_dirs(root: Path) -> int:
    removed = 0
    # Walk bottom-up
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        try:
            # Skip tracked ignore dirs decision here: pruning empty regardless
            if p == root:
                # Never remove the root preview/ directory
                continue
            if not any(p.iterdir()):
                p.rmdir()
                removed += 1
        except Exception:
            continue
    return removed


def _is_ipynb(path: Path) -> bool:
    try:
        return path.suffix.lower() == ".ipynb"
    except Exception:
        return False


def _iter_preview_notebooks_for_strip(
    file_ops: list[FileOp], entries: list[Entry], existed_before: dict[str, bool]
) -> list[Path]:
    """Return absolute Paths of preview notebooks to be stripped.

    - Always includes any .ipynb files that were copied/updated in this run.
    - For folder entries being copied the first time (preview folder did not exist
      before this run), include all .ipynb files under that preview folder to
      ensure they are normalized.
    """
    targets: set[Path] = set()

    # Notebooks touched this run
    for op in file_ops:
        if _is_ipynb(op.dst):
            targets.add(op.dst)

    # First-time folder copies: include all notebooks in the new preview folder
    for e in entries:
        if not e.is_dir:
            continue
        # If the folder did not exist before, include all .ipynb under it
        if not existed_before.get(e.raw, False):
            src_dir = PREVIEW / e.rel
            for rel in _iter_rel_files(src_dir):
                abs_p = src_dir / rel
                if _is_ipynb(abs_p):
                    targets.add(abs_p)

    return sorted(targets, key=lambda p: p.as_posix())


def _strip_notebook_outputs_in_place(path: Path) -> bool:
    """Strip outputs and execution counts from a notebook file.

    Returns True if write succeeded, False otherwise.
    """
    try:
        if _is_symlink(path) or (not path.exists()):
            return False
        nb = nbformat.read(str(path), as_version=4)
        changed = False
        for cell in getattr(nb, "cells", []):
            try:
                if getattr(cell, "cell_type", None) == "code":
                    # Normalize outputs and execution count
                    if getattr(cell, "outputs", None):
                        cell.outputs = []  # type: ignore[attr-defined]
                        changed = True
                    if getattr(cell, "execution_count", None) is not None:
                        cell.execution_count = None  # type: ignore[attr-defined]
                        changed = True
                    # Best-effort metadata cleanup; keep conservative to avoid data loss
                    md = getattr(cell, "metadata", None)
                    if isinstance(md, dict):
                        if "execution" in md:
                            md.pop("execution", None)
                            changed = True
            except Exception:
                # Continue stripping other cells
                continue

        if not changed:
            return True

        text = nbformat.writes(nb)
        _atomic_write(path, text)
        return True
    except Exception as e:
        logger.warning("Failed to strip outputs for %s: %s", path.as_posix(), e)
        return False


def strip_notebook_outputs_in_preview(
    file_ops: list[FileOp], entries: list[Entry], existed_before: dict[str, bool], dry_run: bool
) -> None:
    """Strip outputs in preview notebooks after copy/update.

    No-op on dry_run. Logs warnings on failures and continues.
    """
    if dry_run:
        return
    try:
        targets = _iter_preview_notebooks_for_strip(file_ops, entries, existed_before)
        for p in targets:
            ok = _strip_notebook_outputs_in_place(p)
            if ok:
                logger.debug("Stripped notebook outputs: %s", p.as_posix())
    except KeyboardInterrupt:
        raise
    except Exception as e:
        logger.warning("Notebook strip encountered an issue: %s", e)
        # continue; stripping is best-effort


LOCK_PATH = Path(".classpub.lock")
MARKER_PATH = Path(".sync-in-progress")
LOCK_TTL_SECS = 30


def _is_pid_alive(pid: int) -> bool:
    try:
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _acquire_single_writer_lock(ttl_seconds: int = LOCK_TTL_SECS) -> tuple[bool, str]:
    now_iso = datetime.now(timezone.utc).isoformat()
    hostname = socket.gethostname()
    pid = os.getpid()

    if LOCK_PATH.exists():
        try:
            content = LOCK_PATH.read_text(encoding="utf-8")
            lines = {k: v for k, v in (ln.split(": ", 1) for ln in content.splitlines() if ": " in ln)}
            parsed_ok = True
            try:
                owner_pid = int(lines.get("pid", ""))
            except Exception:
                owner_pid = -1
                parsed_ok = False
            ts_raw = lines.get("time")
            try:
                then = datetime.fromisoformat(ts_raw) if ts_raw else None
            except Exception:
                then = None
                parsed_ok = False

            if not parsed_ok or then is None:
                # Corrupt or incomplete lock → remove and proceed
                LOCK_PATH.unlink(missing_ok=True)
            else:
                age = (datetime.now(timezone.utc) - then).total_seconds()
                if (not _is_pid_alive(owner_pid)) and age > ttl_seconds:
                    # Stale
                    LOCK_PATH.unlink(missing_ok=True)
                else:
                    return False, "busy"
        except Exception:
            # If corrupt, attempt to remove
            try:
                LOCK_PATH.unlink(missing_ok=True)
            except Exception:
                return False, "busy"

    # Try to create exclusively
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid: {pid}\n")
            f.write(f"host: {hostname}\n")
            f.write(f"time: {now_iso}\n")
    except FileExistsError:
        return False, "busy"
    except Exception:
        return False, "error"
    return True, "ok"


def _release_single_writer_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _check_marker_and_maybe_force_full_resync(assume_yes: bool) -> bool:
    """Return True if a full resync should be performed.

    If marker exists and is stale or present, prompt unless assume_yes.
    """
    if not MARKER_PATH.exists():
        return False
    # Determine staleness
    try:
        content = MARKER_PATH.read_text(encoding="utf-8")
        lines = {k: v for k, v in (ln.split(": ", 1) for ln in content.splitlines() if ": " in ln)}
        ts = lines.get("time")
        if ts:
            then = datetime.fromisoformat(ts)
            age = (datetime.now(timezone.utc) - then).total_seconds()
        else:
            age = LOCK_TTL_SECS + 1
    except Exception:
        age = LOCK_TTL_SECS + 1

    is_stale = age > LOCK_TTL_SECS
    if assume_yes and is_stale:
        return True
    # Non-interactive policy: we will prompt; if declined, proceed without full resync
    try:
        sys.stdout.write("⚠️  Previous sync may not have completed cleanly. Perform full resync? [y/N] ")
        sys.stdout.flush()
        raw = sys.stdin.readline()
        if raw == "":
            raise PromptAborted()
        ans = raw.strip()
        return ans in {"y", "Y", "yes"}
    except KeyboardInterrupt:
        raise
    except PromptAborted:
        raise
    except Exception:
        return False


def _write_marker() -> None:
    try:
        MARKER_PATH.write_text(
            f"pid: {os.getpid()}\n" f"time: {datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _remove_marker() -> None:
    try:
        MARKER_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def run_sync(assume_yes: bool, dry_run: bool, console_print: Callable[[str], None]) -> int:
    """Core implementation for the sync command.

    console_print: callable to print to stdout with correct color policy from CLI layer.
    """
    if not _ensure_repo_root():
        console_print("❌ This command must be run from the repository root (missing 'pending/').")
        return 1

    # preview symlink check
    try:
        if PREVIEW.exists() and PREVIEW.is_symlink():
            console_print("❌ preview/ must not be a symlink. Remove it and run again.")
            return 1
    except OSError:
        console_print("❌ Unable to access preview/ to validate symlink status.")
        return 1

    PREVIEW.mkdir(parents=True, exist_ok=True)

    # Acquire single-writer lock
    ok, reason = _acquire_single_writer_lock()
    if not ok:
        if reason == "busy":
            console_print("❌ Another sync is already running. If this is stale, try again shortly.")
            return 75
        console_print("❌ Unable to acquire sync lock.")
        return 1

    # Marker handling
    try:
        force_full = _check_marker_and_maybe_force_full_resync(assume_yes=assume_yes)
    except KeyboardInterrupt:
        _release_single_writer_lock()
        return 130
    except PromptAborted:
        _release_single_writer_lock()
        return 130

    # Write/refresh marker
    _write_marker()

    # Build plan (capture folder pre-existence state)
    entries = read_manifest()
    existed_before: dict[str, bool] = {}
    for e in entries:
        if e.is_dir:
            existed_before[e.raw] = (PREVIEW / e.rel).exists()
    file_ops, per_entry_updated = build_sync_plan(entries, force_full_resync=force_full)

    # Apply copies/updates
    _apply_file_ops(file_ops, dry_run=dry_run)

    # Strip notebook outputs in preview after applying file ops
    try:
        strip_notebook_outputs_in_preview(file_ops, entries, existed_before, dry_run)
    except KeyboardInterrupt:
        _remove_marker()
        _release_single_writer_lock()
        return 130

    # Per-entry counts (updated/unchanged)
    updated_entries = sum(1 for raw, u in per_entry_updated.items() if u)
    unchanged_entries = sum(1 for raw, u in per_entry_updated.items() if not u)

    # Folder messages
    # For now, approximate: if any ops for folder entry => Updated folder (N files)
    ops_by_entry: dict[str, int] = {raw: 0 for raw in per_entry_updated}
    for op in file_ops:
        # attribute op to a matching folder/file entry by longest prefix match
        for e in entries:
            if e.is_dir:
                try:
                    (op.src).relative_to(PENDING / e.rel)
                    ops_by_entry[e.raw] = ops_by_entry.get(e.raw, 0) + 1
                except Exception:
                    continue
            else:
                if (PENDING / e.rel) == op.src:
                    ops_by_entry[e.raw] = ops_by_entry.get(e.raw, 0) + 1

    for e in entries:
        if e.is_dir:
            n = ops_by_entry.get(e.raw, 0)
            src_dir = PENDING / e.rel
            dst_dir = PREVIEW / e.rel
            if not src_dir.exists():
                continue
            if n == 0:
                # Check if empty folder present in pending
                any_files = bool(_iter_rel_files(src_dir))
                if not any_files:
                    console_print(f"📁 Empty folder {e.rel.as_posix()}/")
            else:
                # Decide Copied vs Updated based on dst existence before
                if not existed_before.get(e.raw, dst_dir.exists()):
                    console_print(f"📁 Copied folder {e.rel.as_posix()}/ ({n} files)")
                else:
                    console_print(f"📁 Updated folder {e.rel.as_posix()}/ ({n} files)")

    # Orphan detection and removal
    orphans = _list_orphans(entries)
    removed_files = 0
    if orphans:
        console_print("⚠️  These files will be REMOVED from preview (not in manifest):")
        for rel in orphans[:]:
            console_print(f"     - {rel.as_posix()}")
        if dry_run:
            removed_files = len(orphans)
        else:
            if assume_yes or _prompt_yes():
                removed_files = _remove_files(orphans, dry_run=False)
            else:
                console_print("  Skipped removal")

    try:
        if not dry_run:
            _prune_empty_dirs(PREVIEW)
        # Final summary
        console_print(f"✓ Sync complete: {updated_entries} updated, {removed_files} removed, {unchanged_entries} unchanged")
        return 0
    finally:
        _remove_marker()
        _release_single_writer_lock()


