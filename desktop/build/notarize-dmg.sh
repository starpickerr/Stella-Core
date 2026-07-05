#!/usr/bin/env bash
#
# Notarize + staple a macOS dmg.
#
# Submits ONCE and then polls that same submission id until it reaches a
# terminal state. Never resubmits: a previous version resubmitted on every
# wait timeout, which piled up duplicate "In Progress" submissions in Apple's
# queue and made everything slower.
#
# Notarization is fully automated on Apple's side (malware scan, no humans);
# most submissions finish in minutes, but large bundles or Apple-side backlog
# can take much longer, so we poll patiently instead of failing fast.
#
# Usage: notarize-dmg.sh <path-to-dmg>
# Requires env: APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID
# Tunables: NOTARIZE_MAX_WAIT_MINUTES (default 180), NOTARIZE_POLL_SECONDS (default 60)
set -euo pipefail

DMG="${1:?usage: notarize-dmg.sh <dmg>}"

: "${APPLE_ID:?APPLE_ID not set}"
: "${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD not set}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID not set}"

MAX_WAIT_MINUTES="${NOTARIZE_MAX_WAIT_MINUTES:-180}"
POLL_SECONDS="${NOTARIZE_POLL_SECONDS:-60}"

auth=(
  --apple-id "$APPLE_ID"
  --password "$APPLE_APP_SPECIFIC_PASSWORD"
  --team-id "$APPLE_TEAM_ID"
)

json_field() {
  # json_field <key>  — read a top-level string field from JSON on stdin.
  python3 -c "import json,sys; print(json.load(sys.stdin).get('$1',''))" 2>/dev/null
}

echo "==> Submitting for notarization: $DMG"
submit_out="$(xcrun notarytool submit "$DMG" "${auth[@]}" --no-wait --output-format json)"
submission_id="$(echo "$submit_out" | json_field id)"

if [ -z "$submission_id" ]; then
  echo "::error::could not parse submission id from notarytool output"
  echo "$submit_out"
  exit 1
fi
echo "==> Submission id: $submission_id (uploaded OK, polling status...)"

deadline=$(( $(date +%s) + MAX_WAIT_MINUTES * 60 ))
while :; do
  # info can fail transiently (network); treat as unknown and keep polling.
  status="$(xcrun notarytool info "$submission_id" "${auth[@]}" --output-format json 2>/dev/null | json_field status || true)"
  echo "==> [$(date '+%H:%M:%S')] status: ${status:-<query failed, will retry>}"

  case "$status" in
    Accepted)
      echo "==> Notarization Accepted"
      break
      ;;
    Invalid|Rejected)
      echo "::error::Notarization ${status}; fetching log for diagnostics"
      xcrun notarytool log "$submission_id" "${auth[@]}" || true
      exit 1
      ;;
  esac

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "::error::Notarization still not finished after ${MAX_WAIT_MINUTES} minutes (id: $submission_id)."
    echo "::error::NOT resubmitting. Check later with: xcrun notarytool info $submission_id"
    exit 1
  fi
  sleep "$POLL_SECONDS"
done

echo "==> Stapling ticket into dmg"
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
