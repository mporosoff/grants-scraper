#!/usr/bin/env bash
# Build the full catalog pipeline from frozen fixture inputs, offline.
#
# Usage: tools/hermetic_build.sh <output-dir>
#
# Every network-touching stage is bounded to zero, so this makes no requests.
# Nothing under data/ is read or written; the frozen caches are copied into the
# output directory first, because several stages rewrite their own cache.
#
# Intermediates live in <output-dir>/.work/ and are excluded from fingerprinting.
#
# See docs/TOPIC_LAYER_PLAN.md §8.4.

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <output-dir>" >&2
  exit 2
fi

OUT="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FROZEN="$ROOT/tests/fixtures/frozen"

# The catalog date is fixed so currentness gates resolve identically every run.
AS_OF="2026-08-20"

# Every stage that makes TTL or recheck decisions receives the same fixed
# instant. Pinning only the catalog's generated_at is insufficient because
# document rechecks are evaluated at timestamp (not calendar-day) precision.
PIPELINE_NOW="${AS_OF}T00:00:00Z"

# The change feed derives every event's `changed_at` -- and therefore its event
# id, which is a SHA-1 over `changed_at[:10]` -- from the CURRENT catalog's
# `generated_at`. AS_OF does not reach that value, so before this pin the gate
# was green only on the UTC day its baseline was frozen (docs/TOPIC_LAYER_PLAN.md
# §15 debt D7).
#
# The value is the UTC date the committed baseline was frozen on, chosen so the
# fix costs no re-freeze: the existing fingerprints stay valid. Changing it
# changes every event id and therefore requires tools/freeze_inputs.sh.
GENERATED_AT="2026-08-17T00:00:00Z"

rm -rf "$OUT"
mkdir -p "$OUT/.work"

# Several stages read and then rewrite their cache. Copy, never edit in place.
cp "$FROZEN/opportunity_enrichment.json" \
   "$FROZEN/document_evidence.json" \
   "$FROZEN/source_records.json" "$OUT/"

cd "$ROOT"

# 1. Catalog from the frozen XML archive. --archive skips the download.
#    --min-records 1 because the fixture is small; the live workflow uses 1000.
python -m scripts.build_catalog \
  --archive "$FROZEN/GrantsDBExtract-frozen.zip" \
  --as-of "$AS_OF" \
  --min-records 1 \
  --output "$OUT/opportunities.js" >/dev/null

# Later enrichment and source-merge stages derive currentness from the catalog
# stamp rather than from build_catalog's --as-of argument. Pin the hermetic
# artifact's top-level stamp before those stages so date-bound actionability
# cannot change when this gate crosses a real UTC deadline. Production builds
# do not call this gate-only helper and continue to retain their real timestamp.
python "$ROOT/tools/pin_generated_at.py" \
  "$OUT/opportunities.js" \
  "$OUT/opportunities.js" \
  "${AS_OF}T00:00:00Z"

# Snapshot for change detection, mirroring the workflow's pre-build copy.
cp "$OUT/opportunities.js" "$OUT/.work/opportunities.previous.js"

# 2. Detail enrichment. Zero fetches; still merges the frozen cache.
python -m scripts.enrich_catalog \
  --catalog "$OUT/opportunities.js" \
  --cache "$OUT/opportunity_enrichment.json" \
  --max-updates 0 --max-agency-updates 0 --request-delay 0 \
  --now "$PIPELINE_NOW" >/dev/null

# 3. Canonical source merge. The sample adapter is fixture-backed and offline.
python -m scripts.sources merge \
  --catalog "$OUT/opportunities.js" \
  --cache "$OUT/source_records.json" \
  --adapter sample --include-disabled --write >/dev/null

# 4. Shared document evidence after all sources, matching coordinated refresh.
#    Zero fetches; still merges cached evidence and finalizes indexes/facets.
python -m scripts.extract_document_evidence \
  --catalog "$OUT/opportunities.js" \
  --cache "$OUT/document_evidence.json" \
  --max-documents 0 --request-delay 0 \
  --now "$PIPELINE_NOW" >/dev/null

# 5. Link health. Zero checks; the failure threshold needs >=20 so it cannot trip.
python -m scripts.check_links \
  --catalog "$OUT/opportunities.js" \
  --state "$OUT/link_health.json" \
  --max-checks 0 >/dev/null

# 6. Change events, diffing the post-build snapshot against the final catalog.
#    build_changes reads `generated_at` off --current, so it is given a pinned
#    copy in .work/ rather than the artifact itself. .work/ is excluded from
#    fingerprinting, so opportunities.js stays exactly what the pipeline wrote
#    and only the event stamps become deterministic.
python "$ROOT/tools/pin_generated_at.py" \
  "$OUT/opportunities.js" \
  "$OUT/.work/opportunities.pinned.js" \
  "$GENERATED_AT"
python -m scripts.build_changes \
  --previous "$OUT/.work/opportunities.previous.js" \
  --current "$OUT/.work/opportunities.pinned.js" \
  --out "$OUT/feeds" \
  --as-of "$AS_OF" >/dev/null

# 7. Atom feeds.
python -m scripts.build_feeds \
  --catalog "$OUT/opportunities.js" \
  --out "$OUT/feeds" >/dev/null

# update_catalog_docs is deliberately NOT run: its output paths are hard-coded
# to REPOSITORY_ROOT (README.md, PROJECT.md, match_explorer.html,
# team_match.html) and cannot be redirected, so it would write into the repo.
