from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


# --------------------------
# Defaults (extend-only)
# --------------------------
DEFAULT_IGNORED_FILES: tuple[str, ...] = (
    ".DS_Store",
    ".gitignore",
    ".gitattributes",
    "RELEASES.txt",
)
DEFAULT_IGNORED_DIR_PATTERNS: tuple[str, ...] = (
    ".ipynb_checkpoints/",
)


@dataclass(frozen=True)
class ConfigGeneral:
    strict: bool = False
    assume_yes: bool = False


@dataclass(frozen=True)
class ConfigIgnore:
    patterns: list[str]


@dataclass(frozen=True)
class Config:
    general: ConfigGeneral
    ignore: ConfigIgnore


_ACTIVE_CONFIG: Optional[Config] = None


def get_active_config() -> Config:
    global _ACTIVE_CONFIG
    if _ACTIVE_CONFIG is None:
        _ACTIVE_CONFIG = Config(
            general=ConfigGeneral(),
            ignore=ConfigIgnore(patterns=list(DEFAULT_IGNORED_FILES) + list(DEFAULT_IGNORED_DIR_PATTERNS)),
        )
    return _ACTIVE_CONFIG


def set_active_config(cfg: Config) -> None:
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = cfg


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # type: ignore[import-not-found]
        with path.open("rb") as f:
            return tomllib.load(f)  # type: ignore[attr-defined]
    except Exception:
        try:
            import tomli  # type: ignore[import-not-found]
            with path.open("rb") as f:
                return tomli.load(f)  # type: ignore[attr-defined]
        except Exception:
            raise


def load_project_config(repo_root: Path) -> Config:
    """Load project-local classpub.toml with validation and defaults.

    Precedence: file overrides extend defaults (ignore patterns extend, not replace).
    Unknown keys are ignored with a warning.
    """
    defaults_files = list(DEFAULT_IGNORED_FILES)
    defaults_dirs = list(DEFAULT_IGNORED_DIR_PATTERNS)
    config_path = repo_root / "classpub.toml"

    # Start with defaults
    general = ConfigGeneral()
    patterns: list[str] = defaults_files + defaults_dirs

    if config_path.exists():
        try:
            data = _load_toml(config_path)
        except Exception as e:
            raise ValueError(f"Failed to parse classpub.toml: {e}")

        # general
        gen = data.get("general", {}) if isinstance(data, dict) else {}
        if not isinstance(gen, dict):
            raise ValueError("[general] must be a table")
        strict = gen.get("strict", general.strict)
        assume_yes = gen.get("assume_yes", general.assume_yes)
        if not isinstance(strict, bool):
            raise ValueError("[general.strict] must be a boolean")
        if not isinstance(assume_yes, bool):
            raise ValueError("[general.assume_yes] must be a boolean")
        general = ConfigGeneral(strict=bool(strict), assume_yes=bool(assume_yes))

        # ignore
        ign = data.get("ignore", {}) if isinstance(data, dict) else {}
        if not isinstance(ign, dict):
            raise ValueError("[ignore] must be a table")
        pats = ign.get("patterns", [])
        if pats is None:
            pats = []
        if not isinstance(pats, list) or not all(isinstance(x, str) and x.strip() for x in pats):
            raise ValueError("[ignore.patterns] must be a list of non-empty strings")
        # Normalize and extend defaults
        norm: list[str] = []
        for p in pats:
            s = p.strip()
            # NFC normalization not necessary for simple patterns; keep literal
            if s not in norm:
                norm.append(s)
        patterns = defaults_files + defaults_dirs + norm

        # Warn on unknown keys
        def _warn_unknown(section: str, table: dict, allowed: set[str]) -> None:
            for k in table.keys():
                if k not in allowed:
                    logger.warning("Unknown config key in [%s]: %s", section, k)

        _warn_unknown("general", gen, {"strict", "assume_yes"})
        _warn_unknown("ignore", ign, {"patterns"})

    return Config(general=general, ignore=ConfigIgnore(patterns=patterns))


def compile_ignore_matchers(cfg: Optional[Config] = None) -> tuple[Callable[[str, Optional[str]], bool], Callable[[str, Optional[str]], bool]]:
    """Return (file_matcher, dir_matcher).

    Each matcher takes a base name and an optional posix relative path and returns True if ignored.
    Patterns ending with '/' match directories. Others match files. If a pattern contains '/', we also
    test against the relative path.
    """
    cfg = cfg or get_active_config()
    file_patterns: list[str] = []
    dir_patterns: list[str] = []
    for pat in cfg.ignore.patterns:
        if pat.endswith("/"):
            dir_patterns.append(pat[:-1])
        else:
            file_patterns.append(pat)

    def _match_any(name: str, rel_posix: Optional[str], patterns: list[str]) -> bool:
        for p in patterns:
            try:
                if fnmatch.fnmatchcase(name, p):
                    return True
                if rel_posix and ("/" in p) and fnmatch.fnmatchcase(rel_posix, p):
                    return True
            except Exception:
                continue
        return False

    def file_matcher(name: str, rel_posix: Optional[str]) -> bool:
        return _match_any(name, rel_posix, file_patterns)

    def dir_matcher(name: str, rel_posix: Optional[str]) -> bool:
        # Directory names match by base name or relative posix
        return _match_any(name, rel_posix, dir_patterns)

    return file_matcher, dir_matcher


def ensure_config_loaded(repo_root: Optional[Path] = None) -> Config:
    """Load project config once and set as active. Returns the active config."""
    root = repo_root or Path.cwd()
    try:
        cfg = load_project_config(root)
    except ValueError as e:
        # Surface higher; caller may want to terminate
        raise
    set_active_config(cfg)
    return cfg


