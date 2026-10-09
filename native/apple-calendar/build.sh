#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-$SCRIPT_DIR/.build}"
mkdir -p "$OUT_DIR"
# Command Line Tools contain the EventKit SDK and Swift compiler. Prefer them
# when the developer has not selected a toolchain explicitly; a separate Xcode
# installation may be selected system-wide without its license being accepted.
if [ -z "${DEVELOPER_DIR:-}" ] && [ -x /Library/Developer/CommandLineTools/usr/bin/swiftc ]; then
  export DEVELOPER_DIR=/Library/Developer/CommandLineTools
fi
ARCH="$(uname -m)"
# /usr/bin/swiftc is Apple's toolchain dispatcher. Calling the CLT swiftc
# symlink directly can fail to find its standard library on some machines.
SWIFT_COMPILER=/usr/bin/swiftc
"$SWIFT_COMPILER" -O -target "$ARCH-apple-macos14.0" -framework EventKit \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$SCRIPT_DIR/Info.plist" \
  "$SCRIPT_DIR/CalendarBridge.swift" -o "$OUT_DIR/StellaCalendarBridge"
codesign --force --sign - "$OUT_DIR/StellaCalendarBridge"
