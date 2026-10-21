#!/usr/bin/env bash
#
# Build the desktop backend into a self-contained onedir bundle via PyInstaller.
# Run from anywhere; paths are resolved relative to the repo root.
#
# Local development uses the conda env ``Stella`` only (no project .venv /
# .venv-build). Override with STELLA_PYTHON=... or PYTHON=... if needed.
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

echo "==> Running PyInstaller (onedir) for stella-plugin-runner"
"$PYTHON" -m PyInstaller "$BUILD_DIR/stella-plugin-runner.spec" \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/build-work-runner"

# Build independently owned MCP deliverables; fail the release if either is missing.
for spec in "email_mcp:email" "elearning_crawler:elearning"; do
  MCP_REPO="$ROOT/../MCP/${spec%%:*}"
  MCP_PYTHON="$MCP_REPO/.venv/bin/python"
  if [ ! -x "$MCP_PYTHON" ]; then
    echo "Missing MCP environment: $MCP_REPO (install its build extra first)" >&2
    exit 1
  fi
  "$MCP_PYTHON" "$MCP_REPO/build_mcp.py" --dist-dir "$BUILD_DIR/dist"
done

echo ""
echo "==> Done. Bundles at:"
echo "    $BUILD_DIR/dist/stella-backend/"
echo "    $BUILD_DIR/dist/stella-plugin-runner/"
if [ "$(uname -s)" = "Darwin" ]; then
  bash "$ROOT/native/apple-calendar/build.sh"
fi
du -sh "$BUILD_DIR/dist/stella-backend/" 2>/dev/null || true
du -sh "$BUILD_DIR/dist/stella-plugin-runner/" 2>/dev/null || true
echo "==> Smoke test: STELLA_DESKTOP=1 \"$BUILD_DIR/dist/stella-backend/stella-backend\""
echo "==> Runner: \"$BUILD_DIR/dist/stella-plugin-runner/stella-plugin-runner\""
