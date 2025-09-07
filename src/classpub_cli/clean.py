from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import PENDING, PREVIEW
from .utils import ensure_repo_root_present
from . import sync as sync_mod


logger = logging.getLogger(__name__)


@dataclass
class CleanCounts:
    files_removed: int = 0
    dirs_removed: int = 0


def _is_symlink(p: Path) -> bool:
    try:
        return p.is_symlink()
    except OSError:
        return False


def _remove_ds_store_under(root: Path, counts: CleanCounts) -> None:
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for fname in filenames:
            if fname != ".DS_Store":
                continue
            abs_p = Path(dirpath) / fname
            try:
                if _is_symlink(abs_p):
                    continue
                if abs_p.exists() and abs_p.is_file():
                    abs_p.unlink()
                    counts.files_removed += 1
            except Exception as e:
                logger.error("Failed to remove %s: %s", abs_p.as_posix(), e)
                raise


def _remove_ipynb_checkpoints_under(root: Path, counts: CleanCounts) -> None:
    if not root.exists():
        return
    # Walk to find directories named .ipynb_checkpoints and remove entire trees
    to_remove: list[Path] = []
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        for d in list(dirnames):
            if d == ".ipynb_checkpoints":
                to_remove.append(Path(dirpath) / d)
    # Remove bottom-up
    for d in sorted(to_remove, key=lambda p: p.as_posix(), reverse=True):
        try:
            if _is_symlink(d):
                continue
            if d.exists() and d.is_dir():
                shutil.rmtree(d)
                counts.dirs_removed += 1
        except Exception as e:
            logger.error("Failed to remove directory %s: %s", d.as_posix(), e)
            raise


def run_clean(console_print: Callable[[str], None]) -> int:
    """Remove .DS_Store files and .ipynb_checkpoints directories under pending/ and preview/.

    Returns exit code: 0 on success, 75 if lock contention, 1 on IO/permission errors or invalid repo.
    """
    if not ensure_repo_root_present():
        console_print("❌ This command must be run from the repository root (missing 'pending/').")
        return 1

    ok, reason = sync_mod._acquire_single_writer_lock()  # reuse sync's single-writer lock
    if not ok:
        if reason == "busy":
            console_print("❌ Another operation is already running. If this is stale, try again shortly.")
            return 75
        console_print("❌ Unable to acquire operation lock.")
        return 1

    counts = CleanCounts()
    try:
        # Remove under pending and preview
        for root in (PENDING, PREVIEW):
            try:
                _remove_ds_store_under(root, counts)
                _remove_ipynb_checkpoints_under(root, counts)
            except KeyboardInterrupt:
                raise
            except Exception:
                return 1

        console_print(f"✓ Clean complete: {counts.files_removed} files removed, {counts.dirs_removed} dirs removed")
        return 0
    finally:
        try:
            sync_mod._release_single_writer_lock()
        except Exception:
            pass


