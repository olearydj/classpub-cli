# Classpub CLI — Justfile (lightweight proxies & dev tasks)

[private]
default:
    @just --list

# --- Environment & Setup ---

# Install runtime deps
install:
    uv sync --no-dev

# Install with dev extras (pytest, coverage)
install-dev:
    uv sync

# --- CLI Proxies (prefer these commands) ---

# Show CLI help
help:
    uv run classpub --help

# Show CLI version
version:
    uv run classpub --version

# Initialize manifest (idempotent)
init:
    uv run classpub init

# Validate repository
validate:
    uv run classpub validate

# Mark a file/folder under pending/ for release
release item:
    uv run classpub release "{{item}}"

# Alias for release (git-style naming)
[private]
add item:
    @just release "{{item}}"

# Remove a file/folder from release manifest
remove item:
    uv run classpub remove "{{item}}"

# Implemented commands
check:
    uv run classpub check

# Synchronize files to preview folder
sync args="":
    uv run classpub sync {{args}}
# diff item="":
#     uv run classpub diff {{item}}
to-md args="":
    uv run classpub to-md {{args}}

# Remove file cruft, e.g., .ipynb_checkpoints
clean:
     uv run classpub clean

# Pass-through runner for advanced usage
run *args:
    uv run classpub {{args}}

# --- Testing ---

# Run all tests in quiet mode
test:
    uv run pytest -q

# Run subset: just test-k "pattern"
test-k pattern:
    uv run pytest -q -k "{{pattern}}"

# Coverage summary
cov:
    uv run pytest --cov=classpub_cli --cov-report=term


# --- End-to-End Demo ---

# Remove the sandbox folders
e2e-clean:
    rm -rf sandbox-e2e

# Run an end-to-end test of classpub
e2e:
    bash scripts/e2e-demo.sh


