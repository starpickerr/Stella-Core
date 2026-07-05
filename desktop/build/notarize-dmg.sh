#!/usr/bin/env bash
#
# Notarize + staple a macOS dmg with retry, so a transient notarytool
# status-polling timeout (NSURLErrorDomain -1001) doesn't throw away an
# otherwise-good signed build.
#
# electron-builder's inline notarize aborts the whole build on the first poll
# timeout. Here we retry the submit-and-wait, and before each retry we check
# whether a previous submission already reached a terminal state (Accepted),
# so a flaky poll on an already-successful submission still passes.
#
# Usage: notarize-dmg.sh <path-to-dmg>
# Requires env: APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID
set -euo pipefail

DMG="${1:?usage: notarize-dmg.sh <dmg>}"

: "${APPLE_ID:?APPLE_ID not set}"
: "${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD not set}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID not set}"

MAX_ATTEMPTS="${NOTARIZE_MAX_ATTEMPTS:-5}"

auth=(
  --apple-id "$APPLE_ID"
  --password "$APPLE_APP_SPECIFIC_PASSWORD"
  --team-id "$APPLE_TEAM_ID"
)

# Check whether the most recent submission for this app is already Accepted.
# Used to short-circuit retries when the failure was only a status-poll timeout
# on a submission that Apple actually accepted.
latest_status_is_accepted() {
  local out
  out="$(xcrun notarytool history "${auth[@]}" --output-format json 2>/dev/null || true)"
  # Grab the status of the first (most recent) history entry.
  echo "$out" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    hist = data.get("history", [])
    if hist and hist[0].get("status") == "Accepted":
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
' 2>/dev/null
}

echo "==> Notarizing: $DMG"

attempt=1
while :; do
  echo "==> notarytool submit (attempt ${attempt}/${MAX_ATTEMPTS})"
  if xcrun notarytool submit "$DMG" "${auth[@]}" --wait --timeout 30m; then
    echo "==> Notarization Accepted"
    break
  fi

  echo "::warning::notarytool submit failed on attempt ${attempt}"

  # The submit may have been accepted but the status poll timed out; verify.
  if latest_status_is_accepted; then
    echo "==> Latest submission already Accepted (poll timed out); continuing"
    break
  fi

  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "::error::Notarization failed after ${MAX_ATTEMPTS} attempts"
    exit 1
  fi

  sleep_s=$(( attempt * 30 ))
  echo "==> Retrying in ${sleep_s}s..."
  sleep "$sleep_s"
  attempt=$(( attempt + 1 ))
done

echo "==> Stapling ticket into dmg"
# Staple has its own transient failures; retry a few times.
staple_attempt=1
while :; do
  if xcrun stapler staple "$DMG"; then
    echo "==> Staple OK"
    break
  fi
  if [ "$staple_attempt" -ge 3 ]; then
    echo "::error::Stapling failed after 3 attempts"
    exit 1
  fi
  echo "==> Staple failed, retrying in 15s..."
  sleep 15
  staple_attempt=$(( staple_attempt + 1 ))
done

echo "==> Verifying staple"
xcrun stapler validate "$DMG"
echo "==> Notarization + staple complete: $DMG"
