#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-$SCRIPT_DIR/.build}"
mkdir -p "$OUT_DIR"
ARCH="$(uname -m)"
swiftc -O -target "$ARCH-apple-macos14.0" -framework EventKit \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$SCRIPT_DIR/Info.plist" \
  "$SCRIPT_DIR/CalendarBridge.swift" -o "$OUT_DIR/StellaCalendarBridge"
codesign --force --sign - "$OUT_DIR/StellaCalendarBridge"
