from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

import nbformat
from nbconvert.exporters import MarkdownExporter

from .paths import PENDING, PREVIEW
from .utils import read_manifest, Entry, IGNORED_DIRS, IGNORED_FILES, files_equal


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotebookJob:
    rel: Path                    # relative to pending/, e.g., notebooks/demo.ipynb
    src_path: Path               # source path (pending/rel or preview/rel)
    dest_md: Path                # pending/md/<rel_dir>/<stem>.md
    dest_resources_dir: Path     # pending/md/<rel_dir>/<stem>_files


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def strip_outputs_in_memory(nb) -> None:
    for cell in nb.cells:
        try:
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
                md = cell.setdefault("metadata", {})
                md.pop("execution", None)
                md.pop("collapsed", None)
        except Exception:
            # Be resilient to unexpected cell shapes
            continue


def _iter_manifest_notebooks() -> List[Path]:
    """Return sorted list of relative notebook paths from manifest entries.

    Scans folder entries recursively under PENDING and collects direct file entries
    with the .ipynb suffix. Applies IGNORED_DIRS and IGNORED_FILES.
    """
    entries: list[Entry] = read_manifest()
    rels: set[Path] = set()
    for e in entries:
        if e.is_dir:
            root = PENDING / e.rel
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                # filter ignored dirs in-place
                dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
                for fname in filenames:
                    if fname in IGNORED_FILES:
                        continue
                    if not fname.lower().endswith(".ipynb"):
                        continue
                    abs_path = Path(dirpath) / fname
                    try:
                        if abs_path.is_symlink():
                            continue
                    except OSError:
                        logger.warning("Skipping path due to access issue: %s", abs_path)
                        continue
                    rel = abs_path.relative_to(PENDING)
                    rels.add(rel)
        else:
            if e.rel.suffix.lower() == ".ipynb":
                rels.add(e.rel)
    return sorted(list(rels), key=lambda p: p.as_posix())


def _build_jobs(source: str) -> List[NotebookJob]:
    source = (source or "pending").strip().lower()
    if source not in {"pending", "preview"}:
        raise ValueError("Invalid --source (expected 'pending' or 'preview')")
    src_root = PENDING if source == "pending" else PREVIEW

    jobs: list[NotebookJob] = []
    for rel in _iter_manifest_notebooks():
        src = src_root / rel
        if not src.exists():
            if source == "preview":
                logger.info("Skipping %s (missing in preview/)", rel.as_posix())
            else:
                logger.info("Skipping %s (missing in pending/)", rel.as_posix())
            continue
        # UX nicety: if source=pending and preview exists but raw bytes differ, emit info
        if source == "pending":
            prev = PREVIEW / rel
            try:
                if prev.exists() and not files_equal(PENDING / rel, prev):
                    logger.info("Note: preview differs from pending for %s", rel.as_posix())
            except OSError:
                pass

        dest_md = (PENDING / "md" / rel).with_suffix(".md")
        dest_resources_dir = dest_md.parent / (dest_md.stem + "_files")
        jobs.append(NotebookJob(rel=rel, src_path=src, dest_md=dest_md, dest_resources_dir=dest_resources_dir))
    return jobs


def _execute_in_venv(nb, cwd: Path) -> None:
    # Ensure ipykernel is present
    try:
        import ipykernel  # noqa: F401
    except Exception:
        raise RuntimeError("ipykernel is required for --execute; install with: uv pip install ipykernel")

    # Execute via nbclient with a KernelManager that pins to sys.executable
    from nbclient import NotebookClient
    from jupyter_client import KernelManager

    class VenvKernelManager(KernelManager):
        @property
        def kernel_cmd(self):  # type: ignore[override]
            return [sys.executable, "-m", "ipykernel", "-f", "{connection_file}"]

    client = NotebookClient(
        nb=nb,
        kernel_name="python3",
        kernel_manager_class=VenvKernelManager,
        allow_errors=False,
    )
    client.execute(cwd=str(cwd))


def _export_markdown(nb, resources_dir_name: str) -> tuple[str, dict]:
    exporter = MarkdownExporter()
    resources = {"output_files_dir": resources_dir_name}
    body, res = exporter.from_notebook_node(nb, resources=resources)
    # Normalize line endings and ensure trailing newline
    if not body.endswith("\n"):
        body = body + "\n"
    return body, res


def run_to_md(
    source: str,
    outputs: str,
    execute: bool,
    console_print: Callable[[str], None],
) -> int:
    source = (source or "pending").strip().lower()
    outputs = (outputs or "strip").strip().lower()
    if source not in {"pending", "preview"}:
        console_print("❌ Invalid --source (use 'pending' or 'preview')")
        return 1
    if outputs not in {"strip", "keep"}:
        console_print("❌ Invalid --outputs (use 'strip' or 'keep')")
        return 1

    jobs = _build_jobs(source=source)
    converted = 0

    for job in jobs:
        try:
            nb = nbformat.read(str(job.src_path), as_version=4)

            # Execute first (optional)
            if execute:
                try:
                    _execute_in_venv(nb, cwd=(PENDING / job.rel).parent)
                except RuntimeError as e:
                    console_print(f"❌ {e}")
                    return 1

            # Apply in-memory outputs policy
            if outputs == "strip":
                strip_outputs_in_memory(nb)

            # Export to Markdown with resources
            body, resources = _export_markdown(nb, resources_dir_name=job.dest_resources_dir.name)

            # Write .md
            _atomic_write(job.dest_md, body)

            # Write resources (if any)
            outputs_map = resources.get("outputs", {}) if isinstance(resources, dict) else {}
            if isinstance(outputs_map, dict) and outputs_map:
                job.dest_resources_dir.mkdir(parents=True, exist_ok=True)
                for name, data in outputs_map.items():
                    rel_path = Path(name)
                    # Some exporters prefix with the output_files_dir name; strip it
                    if rel_path.parts and rel_path.parts[0] == job.dest_resources_dir.name:
                        rel_path = Path(*rel_path.parts[1:]) if len(rel_path.parts) > 1 else Path("")
                    target = job.dest_resources_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(data, bytes):
                        target.write_bytes(data)
                    else:
                        target.write_text(str(data), encoding="utf-8")

            converted += 1
            logger.info("Converted %s -> %s", job.rel.as_posix(), job.dest_md.as_posix())
        except Exception as e:
            logger.exception("Failed converting %s: %s", job.rel.as_posix(), e)
            return 1

    console_print(f"✓ Converted: {converted} notebooks")
    return 0


