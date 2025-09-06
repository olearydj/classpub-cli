# Classpub CLI — Justfile (lightweight proxies & dev tasks)

[private]
default:
    @just --list

# --- Environment & Setup ---

# Install runtime deps
install:
    uv sync

# Install with dev extras (pytest, coverage)
install-dev:
    uv sync --extra dev

# --- CLI Proxies (prefer these commands) ---

# Show CLI version
version:
    uv run classpub --version

# Initialize manifest (idempotent)
init:
    uv run classpub init

# Validate required tools & deps (Phase 0)
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

sync args="":
    uv run classpub sync {{args}}
# diff item="":
#     uv run classpub diff {{item}}
# to-md:
#     uv run classpub to-md
# clean:
#     uv run classpub clean

# Pass-through runner for advanced usage
run *args:
    uv run classpub {{args}}

# --- Testing ---

test:
    uv run pytest -q

# Run subset: just test-k "pattern"
test-k pattern:
    uv run pytest -q -k "{{pattern}}"

# Coverage summary
cov:
    uv run pytest --cov=classpub_cli --cov-report=term-missing -q


# --- End-to-End Demo ---

e2e-clean:
    rm -rf sandbox-e2e

e2e-demo:
    # clean sandbox
    rm -rf sandbox-e2e
    mkdir -p sandbox-e2e/pending/notebooks
    # initialize manifest
    cd sandbox-e2e && uv run classpub init
    # create sample file
    echo 'print("Hello World")' > sandbox-e2e/pending/notebooks/hello.py
    # release and check
    cd sandbox-e2e && uv run classpub release notebooks/hello.py
    cd sandbox-e2e && uv run classpub check
    # sync and check
    cd sandbox-e2e && uv run classpub sync --yes
    cd sandbox-e2e && uv run classpub check
    # modify then sync again
    echo 'print("Modified")' > sandbox-e2e/pending/notebooks/hello.py
    cd sandbox-e2e && uv run classpub check
    cd sandbox-e2e && uv run classpub sync --yes
    cd sandbox-e2e && uv run classpub check


