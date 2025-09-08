from __future__ import annotations

import logging
import os
from dataclasses import dataclass
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

from .paths import PENDING, PREVIEW, MANIFEST
from .utils import (
    read_manifest,
    ensure_repo_root_present,
)
from .config import get_active_config, compile_ignore_matchers
from . import utils as utils_mod


logger = logging.getLogger(__name__)


@dataclass
class ValidateCounts:
    errors: int = 0
    warnings: int = 0


def _print_many(lines: Iterable[str], console_print: Callable[[str], None]) -> None:
    for ln in lines:
        console_print(ln)


def _warn(console_print: Callable[[str], None], msg: str, counts: ValidateCounts) -> None:
    counts.warnings += 1
    console_print(f"⚠️  {msg}")


def _error(console_print: Callable[[str], None], msg: str, counts: ValidateCounts) -> None:
    counts.errors += 1
    console_print(f"❌ {msg}")


def _case_collision_messages(root: Path, label: str, limit_groups: int = 50) -> list[str]:
    """Return warning messages for potential case-collisions under root.

    Builds a map of casefolded relative paths to their distinct original spellings.
    Emits one message per group with >1 distinct forms.
    """
    groups: dict[str, set[str]] = {}
    if not root.exists():
        return []
    cfg = get_active_config()
    _file_ignored, dir_ignored = compile_ignore_matchers(cfg)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Consider both directories and files
        rel_dir = Path(dirpath).relative_to(root)
        # Record directories
        for d in list(dirnames):
            if dir_ignored(d, (rel_dir / d).as_posix()):
                continue
            rel = (rel_dir / d).as_posix()
            groups.setdefault(rel.casefold(), set()).add(rel)
        # Record files
        for f in filenames:
            rel = (rel_dir / f).as_posix()
            groups.setdefault(rel.casefold(), set()).add(rel)

    messages: list[str] = []
    for i, originals in enumerate(v for v in groups.values() if len(v) > 1):
        if i >= limit_groups:
            messages.append("  (+more)")
            break
        try:
            a, b = sorted(list(originals))[:2]
        except Exception:
            continue
        messages.append(f"⚠️  Potential case-collision in {label}: {a} vs {b}")
    return messages


def _list_pending_checkpoints(limit: int = 200) -> list[str]:
    lines: list[str] = []
    if not PENDING.exists():
        return lines
    found: list[str] = []
    for dirpath, dirnames, _ in os.walk(PENDING, followlinks=False):
        for d in list(dirnames):
            if d == ".ipynb_checkpoints":
                rel = Path(dirpath).relative_to(PENDING) / d
                found.append(rel.as_posix())
    for rel in sorted(found)[:limit]:
        lines.append(f"⚠️  Found .ipynb_checkpoints under pending/: {rel}")
    if len(found) > limit:
        lines.append(f"  (+{len(found) - limit} more)")
    return lines


def _orphan_preview_folders_messages(tracked_files: set[str], tracked_dirs: set[str], limit: int = 200) -> list[str]:
    lines: list[str] = []
    if not PREVIEW.exists():
        return lines
    cfg = get_active_config()
    _file_ignored, dir_ignored = compile_ignore_matchers(cfg)
    try:
        entries = [p for p in PREVIEW.iterdir() if p.is_dir() and (not dir_ignored(p.name, p.relative_to(PREVIEW).as_posix()))]
    except FileNotFoundError:
        return lines
    except PermissionError:
        return lines

    def _covered_by_tracked_dir(rel_dir: str) -> bool:
        for td in tracked_dirs:
            if rel_dir == td or rel_dir.startswith(td.rstrip("/") + "/"):
                return True
        return False

    def _contains_tracked_file(rel_dir: str) -> bool:
        prefix = rel_dir.rstrip("/") + "/"
        return any(tf.startswith(prefix) for tf in tracked_files)

    found: list[str] = []
    for p in entries:
        rel = p.relative_to(PREVIEW).as_posix()
        if _covered_by_tracked_dir(rel):
            continue
        if _contains_tracked_file(rel):
            continue
        found.append(rel + "/")

    for rel in sorted(found)[:limit]:
        lines.append(f"⚠️  Orphan preview folder: preview/{rel}")
    if len(found) > limit:
        lines.append(f"  (+{len(found) - limit} more)")
    return lines


def run_validate(console_print: Callable[[str], None]) -> int:
    """Execute validation checks and print results to stdout via console_print.

    Returns an exit code (0 on success with warnings allowed; 1 on critical errors).
    """
    counts = ValidateCounts()

    # Dependency checks (Phase 0 behavior retained)
    missing = utils_mod.check_python_deps()
    if missing:
        for name in missing:
            _error(console_print, f"Missing dependency: {name}", counts)
    else:
        console_print("✅ Dependencies OK")

    ok, _ver = utils_mod.git_version_ok()
    if not ok:
        _error(console_print, "Git >= 2.20 required for diff", counts)
    else:
        console_print("✅ Git OK")

    # Doctor-style environment advisories (non-fatal warnings)
    # Git identity
    try:
        name = subprocess.check_output(["git", "config", "--global", "user.name"], text=True).strip()
        email = subprocess.check_output(["git", "config", "--global", "user.email"], text=True).strip()
        if not name or not email:
            _warn(console_print, "Git user.name/email not configured globally", counts)
    except Exception:
        _warn(console_print, "Unable to read git user.name/email (is git installed/configured?)", counts)

    # nbdime git integration (best-effort)
    try:
        tool = subprocess.check_output(["git", "config", "--global", "diff.jupyternotebook.tool"], text=True).strip()
        if tool.lower() != "nbdime":
            _warn(console_print, "Nbdime git integration not detected (diff.jupyternotebook.tool != nbdime)", counts)
    except Exception:
        _warn(console_print, "Nbdime git integration not detected (configure with: nbdime config-git --enable --global)", counts)

    # Structural checks below. If repo root is not present, still report errors but continue.
    if not PENDING.exists():
        _error(console_print, "pending/ is missing", counts)
    if not MANIFEST.exists():
        _error(console_print, "pending/RELEASES.txt is missing", counts)

    try:
        if PREVIEW.exists() and PREVIEW.is_symlink():
            _error(console_print, "preview/ must not be a symlink", counts)
    except OSError:
        _error(console_print, "Unable to access preview/ to validate symlink status", counts)

    if not PREVIEW.exists():
        _warn(console_print, "preview/ is missing (informational)", counts)

    # Manifest-based checks
    entries = read_manifest()
    tracked_dirs: set[str] = {e.rel.as_posix().rstrip("/") + "/" for e in entries if e.is_dir}
    tracked_files: set[str] = {e.rel.as_posix() for e in entries if not e.is_dir}

    # Mixed separators on non-Windows hosts
    if os.name != "nt":
        for e in entries:
            if "\\" in e.raw:
                _warn(console_print, f"Manifest uses Windows separators (\\) in: {e.raw}", counts)

    # Manifest folder presence checks
    for e in entries:
        if not e.is_dir:
            continue
        src_dir = PENDING / e.rel
        dst_dir = PREVIEW / e.rel
        if not src_dir.exists():
            _warn(console_print, f"{e.rel.as_posix()}/ (missing from pending)", counts)
        if PREVIEW.exists() and not dst_dir.exists():
            _warn(console_print, f"preview/{e.rel.as_posix()}/ is missing", counts)

    # Orphan preview folders (top-level) not covered by tracked folders or files
    _print_many(_orphan_preview_folders_messages(tracked_files, tracked_dirs), console_print)
    if _orphan_preview_folders_messages(tracked_files, tracked_dirs):
        # Count the number of warnings just printed (each line begins with ⚠️  )
        counts.warnings += len(_orphan_preview_folders_messages(tracked_files, tracked_dirs))

    # Case-collision warnings
    for root, label in ((PENDING, "pending/"), (PREVIEW, "preview/")):
        msgs = _case_collision_messages(root, label)
        if msgs:
            _print_many(msgs, console_print)
            counts.warnings += len([m for m in msgs if m.startswith("⚠️")])

    # .ipynb_checkpoints under pending
    cp_msgs = _list_pending_checkpoints()
    if cp_msgs:
        _print_many(cp_msgs, console_print)
        counts.warnings += len([m for m in cp_msgs if m.startswith("⚠️")])

    # Optional workflow advisory
    gh = Path(".github") / "workflows" / "publish-public.yml"
    try:
        if Path(".github").exists() and not gh.exists():
            _warn(console_print, "Missing optional workflow: .github/workflows/publish-public.yml", counts)
        elif gh.exists():
            try:
                body = gh.read_text(encoding="utf-8")
                if "OWNER/REPO" in body:
                    _warn(console_print, "Workflow publish-public.yml contains placeholder OWNER/REPO", counts)
            except Exception:
                pass
    except Exception:
        # Non-fatal
        pass

    # Justfile runner advisory
    jf = Path("justfile")
    if jf.exists():
        if shutil.which("just") is None:
            _warn(console_print, "justfile present but 'just' is not installed (brew install just)", counts)

    # Strict mode: escalate warnings to errors per config
    try:
        strict = bool(get_active_config().general.strict)
    except Exception:
        strict = False

    exit_code = 1 if counts.errors > 0 else 0
    if strict and counts.warnings > 0:
        exit_code = 1

    console_print(f"✅ Validate complete: {counts.errors} errors, {counts.warnings} warnings")
    return exit_code


