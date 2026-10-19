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
#   STELLA_PYTHON=/path/to/python bash desktop/build/build-backend.sh
#
# Output: desktop/build/dist/stella-backend/  (folder with the executable)
set -euo pipefail

# --- resolve paths --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR"

pick_python() {
  if [ -n "${STELLA_PYTHON:-}" ] && [ -x "${STELLA_PYTHON}" ]; then
    echo "${STELLA_PYTHON}"
    return
  fi
  if [ -n "${PYTHON:-}" ] && command -v "${PYTHON}" >/dev/null 2>&1; then
    command -v "${PYTHON}"
    return
  fi
  if [ -n "${CONDA_PREFIX:-}" ] && [ "$(basename "${CONDA_PREFIX}")" = "Stella" ] \
    && [ -x "${CONDA_PREFIX}/bin/python" ]; then
    echo "${CONDA_PREFIX}/bin/python"
    return
  fi
  for cand in \
    "/opt/anaconda3/envs/Stella/bin/python" \
    "${HOME}/anaconda3/envs/Stella/bin/python" \
    "${HOME}/miniconda3/envs/Stella/bin/python" \
    "${HOME}/miniforge3/envs/Stella/bin/python" \
    "${HOME}/.conda/envs/Stella/bin/python"; do
    if [ -x "$cand" ]; then
      echo "$cand"
      return
    fi
  done
  if command -v conda >/dev/null 2>&1; then
    if conda run -n Stella which python >/dev/null 2>&1; then
      conda run -n Stella which python
      return
    fi
  fi
  echo "!! Stella conda env not found. Activate it or set STELLA_PYTHON." >&2
  exit 1
}

PYTHON="$(pick_python)"

echo "==> Repo root: $ROOT"
echo "==> Using Python: $($PYTHON --version 2>&1) ($PYTHON)"

# Drop leftover local build venvs from older workflows.
if [ -d "$BUILD_DIR/.venv-build" ]; then
  echo "==> Removing obsolete $BUILD_DIR/.venv-build"
  rm -rf "$BUILD_DIR/.venv-build"
fi

echo "==> Ensuring build dependencies in conda Stella"
"$PYTHON" -m pip install -q --upgrade -c "$ROOT/requirements-security.txt" pip setuptools
if ! "$PYTHON" -m pip install -q -r "$BUILD_DIR/requirements-desktop.txt"; then
  echo "!! Dependency install failed." >&2
  exit 1
fi
"$PYTHON" -m pip install -q -c "$ROOT/requirements-security.txt" pyinstaller

# --- run pyinstaller from repo root so relative datas resolve -------------
cd "$ROOT"
echo "==> Running PyInstaller (onedir) for stella-backend"
"$PYTHON" -m PyInstaller "$BUILD_DIR/stella-backend.spec" \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/build-work"

echo "==> Running PyInstaller (onedir) for stella-plugin-runner"
"$PYTHON" -m PyInstaller "$BUILD_DIR/stella-plugin-runner.spec" \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/build-work-runner"

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
