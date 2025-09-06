from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError


def __getattr__(name: str):  # lazy __version__ accessor
    if name == "__version__":
        try:
            return version("classpub-cli")
        except PackageNotFoundError:
            return "0.0.0"
    raise AttributeError(name)

