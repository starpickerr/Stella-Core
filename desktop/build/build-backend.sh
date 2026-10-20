#!/usr/bin/env bash
#
# Build the desktop backend into a self-contained onedir bundle via PyInstaller.
# Run from anywhere; paths are resolved relative to the repo root.
#
# Usage:
#   bash desktop/build/build-backend.sh            # build
#   PYTHON=/path/to/conda/envs/Stella/bin/python bash desktop/build/build-backend.sh   # pick interpreter
#
# Output: desktop/build/dist/stella-backend/  (folder with the executable)
set -euo pipefail

# --- resolve paths --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR"
# Use the same existing Conda environment as source startup and tests.
# PYTHON remains an explicit override for controlled build/CI environments.
if [ -z "${PYTHON:-}" ]; then
  PYTHON="$(python3 "$ROOT/scripts/check_runtime.py")"
fi
"$PYTHON" -c 'import sys; print("==> Using Python:", sys.executable, sys.version.split()[0])'

echo "==> Installing build dependencies"
"$PYTHON" -m pip install -q --upgrade -c "$ROOT/requirements-security.txt" pip setuptools
"$PYTHON" -m pip install -q -r "$BUILD_DIR/requirements-desktop.txt"
"$PYTHON" -m pip install -q -c "$ROOT/requirements-security.txt" pyinstaller

# --- run pyinstaller from repo root so relative datas resolve -------------
cd "$ROOT"
echo "==> Running PyInstaller (onedir)"
"$PYTHON" -m PyInstaller "$BUILD_DIR/stella-backend.spec" \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/build-work"

echo ""
echo "==> Done. Bundle at: $BUILD_DIR/dist/stella-backend/"
if [ "$(uname -s)" = "Darwin" ]; then
  bash "$ROOT/native/apple-calendar/build.sh"
fi
du -sh "$BUILD_DIR/dist/stella-backend/" 2>/dev/null || true
echo "==> Smoke test: STELLA_DESKTOP=1 \"$BUILD_DIR/dist/stella-backend/stella-backend\""
