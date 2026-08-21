#!/usr/bin/env bash
# Regenerate the frozen fixture inputs and the no-drift baseline.
#
# Usage: tools/freeze_inputs.sh
#
# Run this once when setting the gate up, and again only when a change to
# flag-off output is INTENDED. It reads data/ but never writes there.
#
# The frozen caches are trimmed to the opportunity ids present in the frozen
# XML archive. The live caches are keyed by real Grants.gov ids, which do not
# intersect the fixture's ids, so the trim itself yields empty caches.
#
# The hand-authored entries in tests/fixtures/frozen/authored/ are then merged
# on top. They are what brings the *populated* merge paths -- merge_detail and
# merge_document_entry -- under the gate, and merging them here rather than
# editing the frozen caches by hand means re-running this script cannot
# silently delete that coverage. A live entry for the same id wins, so this
# stays correct if the fixture ids ever do intersect the live caches.
#
# See docs/TOPIC_LAYER_PLAN.md §8.4 and §18.1 item A1.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FROZEN="$ROOT/tests/fixtures/frozen"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cd "$ROOT"
mkdir -p "$FROZEN"

# 1. Deterministic zip of the existing XML fixture. Built with Python rather
#    than zip(1): the timestamps must be pinned or the archive hash moves, and
#    zip(1) is not present in every environment this runs in.
python - "$FROZEN/GrantsDBExtract-frozen.zip" <<'PYTHON'
import pathlib
import sys
import zipfile

source = pathlib.Path("tests/fixtures/grants_db_extract.xml")
target = pathlib.Path(sys.argv[1])
info = zipfile.ZipInfo("GrantsDBExtract-frozen.xml", date_time=(1980, 1, 1, 0, 0, 0))
info.compress_type = zipfile.ZIP_DEFLATED
info.external_attr = 0o644 << 16
with zipfile.ZipFile(target, "w") as archive:
    archive.writestr(info, source.read_bytes())
print(f"froze {target.name} ({target.stat().st_size} bytes)")
PYTHON

# 2. Build a throwaway catalog from that archive to learn which ids it carries.
python -m scripts.build_catalog \
  --archive "$FROZEN/GrantsDBExtract-frozen.zip" \
  --as-of 2026-08-20 --min-records 1 \
  --output "$WORK/probe.js" >/dev/null

# 3. Trim the live caches to those ids, then merge the hand-authored entries.
python - "$WORK/probe.js" "$FROZEN" <<'PYTHON'
import json
import pathlib
import sys

probe, frozen = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])


def authored(name):
    """Hand-authored entries for `name`, keyed by opportunity id.

    Keys beginning with an underscore are documentation, not records.
    """
    source = frozen / "authored" / f"{name}.json"
    if not source.exists():
        return {}
    payload = json.loads(source.read_text(encoding="utf-8"))
    return {
        key: value
        for key, value in (payload.get("records") or {}).items()
        if not key.startswith("_")
    }


payload = probe.read_text(encoding="utf-8")
catalog = json.loads(
    payload.split("globalThis.GRANT_CATALOG=", 1)[1].strip().rsplit(";", 1)[0]
)
keep = {
    str(record.get("opportunity_id") or record.get("opportunity_number"))
    for record in catalog["opportunities"]
}

for name in ("opportunity_enrichment", "document_evidence"):
    data = json.loads(
        pathlib.Path("data", f"{name}.json").read_text(encoding="utf-8")
    )
    before = len(data.get("records") or {})
    trimmed = {
        key: value
        for key, value in (data.get("records") or {}).items()
        if key in keep
    }
    hand_authored = {
        key: value
        for key, value in authored(name).items()
        if key in keep and key not in trimmed
    }
    data["records"] = dict(
        sorted({**trimmed, **hand_authored}.items())
    )
    data["generated_at"] = "2026-08-20T00:00:00Z"
    (frozen / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"froze {name}.json ({before} live -> {len(trimmed)} trimmed "
        f"+ {len(hand_authored)} hand-authored = {len(data['records'])})"
    )

# Source snapshots are per-adapter and the hermetic run uses only the fixture
# adapter, so the cache starts empty and the run repopulates it.
source_records = json.loads(
    pathlib.Path("data", "source_records.json").read_text(encoding="utf-8")
)
source_records["sources"] = {}
(frozen / "source_records.json").write_text(
    json.dumps(source_records, ensure_ascii=False, separators=(",", ":")) + "\n",
    encoding="utf-8",
    newline="\n",
)
print("froze source_records.json (reset to 0 sources)")
PYTHON

# 4. Build once and record the baseline.
"$ROOT/tools/hermetic_build.sh" "$WORK/build"
python "$ROOT/tools/fingerprint.py" "$WORK/build" \
  > "$ROOT/evaluation/artifact_fingerprints.txt"

echo
echo "Wrote evaluation/artifact_fingerprints.txt ($(wc -l < "$ROOT/evaluation/artifact_fingerprints.txt" | tr -d ' ') artifacts)"
echo "Review the diff before committing, then:"
echo "  git add tests/fixtures/frozen evaluation/artifact_fingerprints.txt"
