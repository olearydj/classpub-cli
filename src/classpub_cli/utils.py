from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple


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


