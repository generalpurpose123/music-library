#!/usr/bin/env bash
# One-command dev setup: creates .venv, installs the package, scaffolds .env.
# Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3.14 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "error: Python 3.14+ is required but was not found." >&2
    echo "Install it (e.g. 'pyenv install 3.14' or from python.org) and re-run." >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "warning: ffmpeg not found — required for audio conversion."
    echo "         Install with: sudo apt install ffmpeg  (or: brew install ffmpeg)"
fi

# shazamio-core ships no Python 3.14 wheels yet, so pip builds it from source
# (Rust is bootstrapped automatically). On Linux that build needs pkg-config
# and the ALSA headers — check before spending minutes on a doomed compile.
if [ "$(uname -s)" = "Linux" ]; then
    if ! command -v pkg-config >/dev/null 2>&1 || ! pkg-config --exists alsa 2>/dev/null; then
        echo "error: building shazamio-core requires pkg-config and the ALSA dev headers." >&2
        echo "       Install with: sudo apt install pkg-config libasound2-dev" >&2
        exit 1
    fi
fi

[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -e '.[dev]'
[ -f .env ] || cp .env.example .env

echo
echo "Setup complete. Next steps:"
echo "  1. Add Spotify credentials to .env (or do it later in the web UI's settings page)"
echo "  2. Run the app:    ./.venv/bin/uvicorn frontend.server:app --reload"
echo "  3. Run the tests:  ./.venv/bin/pytest -q"
