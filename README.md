# classpub-cli

Course publishing CLI for managing a three-stage content workflow: develop in `pending/`, stage in `preview/`, and publish to a student-facing repo. It replaces a large `justfile` with a tested, maintainable Python CLI.

## Overview

- Three-stage system:
  - `pending/` – development workspace (keeps outputs)
  - `preview/` – local staging (generated; outputs stripped)
  - Student repo – published by CI
- Release manifest controls publication: `pending/RELEASES.txt` (files and tracked folders; folders end with `/`).
- Content-aware status and sync with “touched” detection (newer mtime, identical content).
- Exact output and UX are specified in TDD.md; logs go to stderr, user-facing results to stdout.

## Key Features

- Mark files or folders for release with trailing-slash semantics
- Accurate status: synced / touched / modified / staged / untracked / removed
- Sync with removal prompt and notebook output stripping
- Diffs using `git diff --no-index` for text, `nbdime` for notebooks
- Convert synchronized notebooks to Markdown via `nbconvert`
- Validate repository structure; clean `.DS_Store` and `.ipynb_checkpoints`

## Requirements

- Python 3.10+
- [Git](https://git-scm.com/) CLI ≥ 2.20 for version control, etc.
  - e.g. `brew install git`
- [just](https://github.com/casey/just) command runner used by the generated Justfile
  - e.g. `brew install just`

Python libraries (installed with the package):
- Typer, Rich, nbformat, nbdime (Python API), nbconvert, nbstripout

## Required: nbdime Git integration for notebook diffs

`classpub diff` uses `git diff --no-index` for all files. For notebooks, Git must be configured to use `nbdime` as the diff driver. Configure it once globally or add a repo‑local `.gitattributes`.

```bash
# Enable nbdime globally for notebook diffs
nbdime config-git --enable --global

# Ensure nbdime is the default notebook diff tool
git config --global diff.jupyternotebook.tool nbdime

# Verify configuration
git config --global --list | grep nbdime
```

Repo‑local alternative (committable): add `.gitattributes` with:

```
*.ipynb diff=jupyternotebook
```

## Installation (project-local with uv)

```bash
# Add classpub-cli to your project and create venv
uv init  # ensure pyproject.toml exists before add
uv add --dev classpub-cli
uv sync
```

The CLI entry point is `classpub`. The generated Justfile calls it via `uv run classpub`.

## Quick Start

```bash
# One-time project setup (scaffolds files and end-user justfile)
uv run classpub setup

# Mark items for release (files or folders)
just add notebooks/01-intro.ipynb
just add data/

# Check repository status
just check

# Sync released items to preview (prompts before removals)
just sync

# Optional: diff, convert to markdown, validate, clean
just diff
just to-md
just validate
just clean
```

## Commands (Essentials)

- `init` – Create `pending/RELEASES.txt` if missing (idempotent)
- `add | release <item>` – Mark a file or folder for release; folders end with `/`
- `remove <item>` – Remove from manifest; hints to run `classpub sync` if still in preview
- `check` – Show status for tracked items and orphans in preview
- `sync` – Copy/update released items to preview; prompt to remove orphans; strip notebook outputs
  - Options: `--yes/-y` (auto-approve removals), `--dry-run`
- `diff [item]` – Show diffs for files and folder summaries; notebooks via Git’s `nbdime` driver
- `to-md` – Convert synchronized notebooks to Markdown under `pending/md/...`
- `validate` – Verify structure and common pitfalls
- `clean` – Remove `.DS_Store` files and `.ipynb_checkpoints` directories

See TDD.md §7 for precise behaviors, output strings, and exit codes.

## Status Icons (in `check`)

- `✅` synced
- `👆` touched (newer mtime, identical content)
- `🔄` modified
- `📋` staged
- `📄` untracked
- `⚠️` removed (orphan in preview)

## Configuration

Project-local config file: `classpub.toml` (no user-level config). CLI flags override config which overrides defaults.

Example:
```toml
# classpub.toml

[general]
# strict = false
# assume_yes = false
# color = true

[sync]
# dry_run = false
# large_file_warn_mb = 100

[ignore]
# patterns = [
#   ".DS_Store",
#   ".gitignore",
#   ".gitattributes",
#   ".ipynb_checkpoints/",
#   "RELEASES.txt",
# ]

[hash]
# chunk_size = 8192

[logging]
# level = "INFO"     # ERROR, WARNING, INFO, DEBUG
# format = "human"   # human, json
# timestamps = true
```

Initialize a commented template:
```bash
classpub config init
```

## Logging & Output

- User-facing results → stdout (Rich formatting in human mode)
- Logs → stderr only (human or JSON)
- A file log is written at ≥ INFO to a platform-specific user log directory
- In JSON mode or with `--no-color`, Rich styling is disabled

## Safety

- Absolute input paths must resolve under `pending/`
- `preview/` must not be a symlink (error)
- Removals are prompted unless `--yes` or configured
- Notebook outputs are stripped in `preview/` after sync

## Path & Unicode Policy

- Manifest lines always use forward slashes (`/`)
- Inputs with platform separators are normalized to `/` for matching
- Store/display original paths; normalize to NFC for comparisons only

## Development

```bash
# run tests with coverage
pytest -q --cov=classpub_cli --cov-report=term-missing

# lint/style (if configured)
```

### Jupyter kernel (optional, for --execute)

The `--execute` flag in `classpub to-md` runs notebooks in the current virtual environment via `ipykernel`.

- Install dev dependencies (includes `ipykernel`) with uv:
  - `uv sync` (dev group is included by default), or `uv sync --dev`
- Verify `ipykernel` is available:
  - `uv run python -c "import ipykernel; print(ipykernel.__version__)"`
- (Optional) Install a kernelspec for local Jupyter use:
  - `uv run python -m ipykernel install --user --name "classpub-test" --display-name "classpub-test"`

Notes:
- `ipykernel` does not provide a `ipykernel` console script; use `python -m ipykernel`.
- If you don’t use `--execute`, `ipykernel` is not required.

Performance targets and methodology are documented in TDD.md §11.1.

## Roadmap

See TDD.md §21 for the phased implementation plan (Phase 0 → Phase 10), including scopes, tests, and exit criteria.

## License

See repository licensing files (to be finalized).


