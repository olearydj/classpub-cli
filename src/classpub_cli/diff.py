from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .paths import PENDING, PREVIEW
from .utils import (
    Entry,
    Resolution,
    Resolved,
    dir_diff,
    git_version_ok,
    format_ambiguity_list,
    format_grouped_listing_for_not_found,
    read_manifest,
    resolve_item,
)


HEADER_ALL = "📊 Diff: preview vs pending (tracked files only)"
NO_DIFFS = "✅ No differences found between tracked files"


def _ensure_git_ready() -> bool:
    ok, _ = git_version_ok()
    return ok


def _entry_from_manifest_token(token: str) -> Optional[Entry]:
    """Return a manifest entry matching the token's canonical form, if any.

    This allows item-mode diff to target entries that are in the manifest even
    when the corresponding path may not currently exist under pending/.
    """
    tok = token.strip().replace("\\", "/")
    if tok.startswith("pending/"):
        tok = tok[len("pending/") :]
    prefer_dir = tok.endswith("/")
    tok_no_slash = tok[:-1] if prefer_dir else tok
    entries = read_manifest()
    for e in entries:
        raw = e.raw  # already includes trailing slash for dirs
        if raw == tok or raw == tok_no_slash or (prefer_dir and raw == tok):
            return e
    return None


def _run_git_diff(console_print: Callable[[str], None], preview_path: Path, pending_path: Path) -> int:
    """Run git diff --no-index between preview and pending paths.

    Returns git's return code. 0 means no differences, 1 means differences.
    Any other code indicates an error invoking git.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--no-index", "--", str(preview_path), str(pending_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        # Forward stdout to our console printer so test runner captures it
        if proc.stdout:
            for line in proc.stdout.splitlines():
                if line is not None:
                    console_print(line)
        return proc.returncode
    except Exception:
        # Treat as an error; caller decides message/exit
        return 2


def _print_folder_summary(rel: Path, console_print: Callable[[str], None], per_section_limit: int = 200) -> bool:
    """Print a folder change summary. Returns True if anything was printed."""
    src = PENDING / rel
    dst = PREVIEW / rel
    added, removed, changed = dir_diff(src, dst)
    if not added and not removed and not changed:
        return False

    rel_header = rel.as_posix()
    if not rel_header.endswith("/"):
        rel_header += "/"
    console_print(f"📁 {rel_header} (folder has changes)")

    def _emit_section(title: str, items: list[Path]) -> None:
        if not items:
            return
        console_print(f"{title}")
        limit = min(per_section_limit, len(items))
        for i in range(limit):
            console_print(f"  {items[i].as_posix()}")
        if len(items) > per_section_limit:
            console_print(f"  (+{len(items) - per_section_limit} more)")

    _emit_section("Added:", added)
    _emit_section("Removed:", removed)
    _emit_section("Changed:", changed)
    return True


def _diff_file(rel: Path, console_print: Callable[[str], None]) -> int:
    """Diff a single file if present on both sides. Returns git exit code (0/1) or 2 on error.

    Does not print any informational messages; caller handles side-only cases.
    """
    src = PENDING / rel
    dst = PREVIEW / rel
    if src.exists() and dst.exists():
        return _run_git_diff(console_print, dst, src)
    return 0


def run_diff_all(console_print: Callable[[str], None]) -> int:
    """No-arg diff: iterate manifest entries and print results.

    Returns process exit code: 0 (even when diffs exist). Only returns 1 on fatal errors.
    """
    if not _ensure_git_ready():
        console_print("❌ Git >= 2.20 required for diff")
        return 1

    console_print(HEADER_ALL)

    any_output = False
    entries: list[Entry] = read_manifest()
    for e in entries:
        if e.is_dir:
            if (PENDING / e.rel).exists() and (PREVIEW / e.rel).exists():
                printed = _print_folder_summary(e.rel, console_print)
                any_output = any_output or printed
            # In no-arg mode we do not print side-only info messages for folders
        else:
            # Only run git diff when both exist; otherwise skip silently in no-arg mode
            code = _diff_file(e.rel, console_print)
            if code == 1:
                # Differences printed by git
                any_output = True
            elif code not in (0, 1):
                # Error invoking git
                return 1

    if not any_output:
        console_print(NO_DIFFS)
    return 0


def run_diff_item(token: str, console_print: Callable[[str], None]) -> int:
    """Item-mode diff: resolve like release/remove and act accordingly.

    Returns 0 on success, 1 on resolution or process errors.
    """
    if not _ensure_git_ready():
        console_print("❌ Git >= 2.20 required for diff")
        return 1

    res: Resolved = resolve_item(token)
    if res.status.name == "ERROR":
        console_print(f"❌ {res.message}")
        return 1
    if res.status.name == "NOT_FOUND":
        # If the item is in the manifest, allow item-mode info behavior even if pending path is missing
        m = _entry_from_manifest_token(token)
        if m is None:
            console_print(f"❌ File or folder not found: {token}")
            for line in format_grouped_listing_for_not_found():
                console_print(line)
            return 1
        # Use manifest entry details for subsequent logic
        rel: Path = m.rel
        if m.is_dir:
            rel_disp = rel.as_posix() + ("/" if not rel.as_posix().endswith("/") else "")
            src_dir = PENDING / rel
            dst_dir = PREVIEW / rel
            if dst_dir.exists() and not src_dir.exists():
                console_print(f"ℹ️  {rel_disp} exists in preview but not in pending")
                return 0
            if src_dir.exists() and not dst_dir.exists():
                # If no files under pending folder, suppress output per no-change policy
                added, removed, changed = dir_diff(src_dir, dst_dir)
                if not added and not removed and not changed:
                    return 0
                console_print(f"ℹ️  {rel_disp} exists in pending but not in preview")
                return 0
            # Both missing: informational
            console_print(f"ℹ️  {rel_disp} does not exist in pending or preview")
            return 0
        else:
            src = PENDING / rel
            dst = PREVIEW / rel
            rel_disp = rel.as_posix()
            if dst.exists() and not src.exists():
                console_print(f"ℹ️  {rel_disp} exists in preview but not in pending")
                return 0
            if src.exists() and not dst.exists():
                console_print(f"ℹ️  {rel_disp} exists in pending but not in preview")
                return 0
            console_print(f"ℹ️  {rel_disp} does not exist in pending or preview")
            return 0
    if res.status.name == "AMBIGUOUS":
        console_print(f"❌ Ambiguous item: {token}")
        for line in format_ambiguity_list(res.candidates or []):
            console_print(line)
        return 1

    # If resolution did not yield a concrete path (e.g., folder exists only in preview),
    # fall back to manifest entry matching to determine type and rel path.
    rel: Optional[Path] = res.rel
    is_dir: Optional[bool] = res.is_dir
    if rel is None or is_dir is None:
        m = _entry_from_manifest_token(token)
        if m is not None:
            rel = m.rel
            is_dir = m.is_dir
    if rel is None or is_dir is None:
        # Should not happen often; treat as not found for safety
        console_print(f"❌ File or folder not found: {token}")
        return 1

    if res.is_dir:
        src_dir = PENDING / rel
        dst_dir = PREVIEW / rel
        if src_dir.exists() and dst_dir.exists():
            # Only print when there are changes
            printed = _print_folder_summary(rel, console_print)
            # If no changes, print nothing
            return 0
        # If preview folder is missing entirely (e.g., just synced created no files), treat as pending-only
        rel_disp = rel.as_posix() + ("/" if not rel.as_posix().endswith("/") else "")
        if src_dir.exists() and not dst_dir.exists():
            # If the pending folder is empty (no files under it), treat as no output
            added, removed, changed = dir_diff(src_dir, dst_dir)
            if not added and not removed and not changed:
                return 0
            console_print(f"ℹ️  {rel_disp} exists in pending but not in preview")
            return 0
        if dst_dir.exists() and not src_dir.exists():
            console_print(f"ℹ️  {rel_disp} exists in preview but not in pending")
            return 0
        console_print(f"ℹ️  {rel_disp} does not exist in pending or preview")
        return 0
    else:
        src = PENDING / rel
        dst = PREVIEW / rel
        if src.exists() and dst.exists():
            code = _run_git_diff(console_print, dst, src)
            if code in (0, 1):
                return 0
            return 1
        rel_disp = rel.as_posix()
        if src.exists() and not dst.exists():
            console_print(f"ℹ️  {rel_disp} exists in pending but not in preview")
            return 0
        if dst.exists() and not src.exists():
            console_print(f"ℹ️  {rel_disp} exists in preview but not in pending")
            return 0
        console_print(f"ℹ️  {rel_disp} does not exist in pending or preview")
        return 0


