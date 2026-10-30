#!/usr/bin/env bash
# One-time host setup (Linux / macOS / WSL): creates .venv and installs requirements.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3, 8), "Python 3.8+ required"'
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
if [ -d wheels ] && ls wheels/*.whl >/dev/null 2>&1; then
    .venv/bin/python -m pip install --no-index --find-links wheels -r requirements.txt   # offline
else
    .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python -c "import numpy, matplotlib, msgpack; print('OK: numpy', numpy.__version__)"
echo "Setup complete. Use ./osii.sh <command> (see README.md)."
