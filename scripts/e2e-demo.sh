#!/usr/bin/env bash
set -euo pipefail

# Run from repo root. This script exercises the e2e demo used in the Just recipe.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

SANDBOX="sandbox-e2e"
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX/pending/notebooks"

# init manifest
(cd "$SANDBOX" && uv run classpub init)

# sample file and notebook (with outputs)
echo 'print("Hello World")' > "$SANDBOX/pending/notebooks/hello.py"
uv run python -c "import nbformat; from pathlib import Path; nb=nbformat.v4.new_notebook(); c=nbformat.v4.new_code_cell(source='print(\"hello\")\n', execution_count=2); c.outputs=[nbformat.v4.new_output(output_type='stream', name='stdout', text='hello\n')]; nb.cells.append(c); p=Path('$SANDBOX/pending/notebooks/demo.ipynb'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(nbformat.writes(nb), encoding='utf-8')"

# release file and folder
(cd "$SANDBOX" && uv run classpub release notebooks/hello.py)
(cd "$SANDBOX" && uv run classpub release notebooks/)
(cd "$SANDBOX" && uv run classpub check)

# sync and check
(cd "$SANDBOX" && uv run classpub sync --yes)
(cd "$SANDBOX" && uv run classpub check)

# verify notebook in preview is stripped
grep -q '"execution_count": null' "$SANDBOX/preview/notebooks/demo.ipynb"
grep -q '"outputs": \[\]' "$SANDBOX/preview/notebooks/demo.ipynb"

# idempotent second sync; folder shows as synced
(cd "$SANDBOX" && uv run classpub sync --yes)
(cd "$SANDBOX" && uv run classpub check | grep -q '✅ notebooks/')

# modify then sync again
echo 'print("Modified")' > "$SANDBOX/pending/notebooks/hello.py"
(cd "$SANDBOX" && uv run classpub check)
(cd "$SANDBOX" && uv run classpub sync --yes)
(cd "$SANDBOX" && uv run classpub check)

# orphan dry-run and removal
echo '{}' > "$SANDBOX/preview/stray.ipynb"
out=$(cd "$SANDBOX" && uv run classpub sync --dry-run)
echo "$out" | grep -q '     - stray.ipynb'
echo "$out" | grep -qv 'Continue with removal?'
(cd "$SANDBOX" && uv run classpub sync --yes)
test ! -f "$SANDBOX/preview/stray.ipynb"

# preview symlink rejection (exit code + message)
rm -rf "$SANDBOX/preview"
mkdir -p "$SANDBOX/_target"
ln -s _target "$SANDBOX/preview"
set +e
(cd "$SANDBOX" && uv run classpub sync --yes > out.txt 2>&1)
code=$?
set -e
test "$code" -eq 1
grep -q 'must not be a symlink' "$SANDBOX/out.txt"

echo '✅ e2e demo completed successfully'


