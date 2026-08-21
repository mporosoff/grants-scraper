#!/usr/bin/env bash
# The hermetic no-drift gate. Rebuild from frozen inputs and compare against
# the committed baseline.
#
# Usage: tools/verify_no_drift.sh
#
# Runs in CI on every push and pull request (.github/workflows/tests.yml).
# Makes no network requests and never touches data/.
#
# A failure means flag-off output changed. See docs/TOPIC_LAYER_PLAN.md §0.5.
# If the change was intended, re-run tools/freeze_inputs.sh and review the
# resulting diff to evaluation/artifact_fingerprints.txt line by line.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASELINE="$ROOT/evaluation/artifact_fingerprints.txt"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ ! -f "$BASELINE" ]; then
  echo "Missing baseline: $BASELINE" >&2
  echo "Run tools/freeze_inputs.sh first." >&2
  exit 2
fi

"$ROOT/tools/hermetic_build.sh" "$WORK/build"
python "$ROOT/tools/fingerprint.py" "$WORK/build" > "$WORK/current.txt"

if diff -u "$BASELINE" "$WORK/current.txt"; then
  echo "no-drift: OK ($(wc -l < "$BASELINE" | tr -d ' ') artifacts unchanged)"
else
  cat >&2 <<'MESSAGE'

DRIFT: flag-off output changed. See docs/TOPIC_LAYER_PLAN.md §0.5.

Every generated artifact must be byte-identical to what the current code
produces from the same inputs. A line above that differs names an artifact
whose content changed.

If this change was NOT intended, the change that caused it is wrong.
If it WAS intended, re-run tools/freeze_inputs.sh and review the resulting
diff to evaluation/artifact_fingerprints.txt before committing it.
MESSAGE
  exit 1
fi
