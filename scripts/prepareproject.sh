#!/usr/bin/env bash
set -euo pipefail

echo "==> Custom prepareproject.sh starting..."

# Detect venv path (standard in many builders)
VENV_PATH="${VENV_PATH:-/project/the_venv}"
if [ ! -d "$VENV_PATH" ]; then
    echo "==> Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
fi

source "$VENV_PATH/bin/activate"

echo "==> Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

# Fix for Arango serviceMaker bug: space in scipy filename
# We delete the offending test file if it exists to prevent broken scripts from failing
echo "==> Checking for problematic scipy files..."
OFFENDING_FILE="$VENV_PATH/lib/python3.13/site-packages/scipy/io/tests/data/Transparent Busy.ani"
if [ -f "$OFFENDING_FILE" ]; then
    echo "==> Removing problematic file: $OFFENDING_FILE"
    rm "$OFFENDING_FILE"
fi

# Also check other possible python versions if 3.13 is just an example
find "$VENV_PATH/lib" -name "Transparent Busy.ani" -delete || true

echo "==> Dependencies installed successfully."
