"""P7.1's measurement frame, defined and enumerated offline before any outcome
is read.

**Why this file exists.** `docs/TOPIC_LAYER_PLAN.md` **DEBT-11** records that the
stratified sampling instrument behind the survey and the taxonomy was never
committed, so neither draw can be reproduced and an exclusion set can only ever
be approximate. P7.1 is a measurement session, so it owes its own frame the
treatment DEBT-11 asks for: **inclusion rules first, record ids enumerated
deterministically, the frame pinned before its outcomes are interpreted.**

Three frames, and they are never pooled into one denominator:

* **Frame R -- the historical form-bearing set.** Every catalog record a
  *committed* artifact names as carrying an observed instance of form F1, F3, F4
  or F5, plus `Fm8`'s one `Priority Area N` observation and the three records
  P5's closeout requires as P7 false-positive fixtures. This is a **census of the
  historical evidence**, not a sample: its denominator is "records previously
  observed to carry this form", and no catalog rate may be computed from it.
* **Frame S -- the `Fm8` document-surface sample.** A seeded simple random draw
  from every catalog record with a fetchable text surface under production's own
  rules. Deliberately **uncapped by agency**, unlike the survey/taxonomy/Cov7
  draws: an agency cap protects a *form* estimate from one template being read
  three times, but it biases a *label-prevalence* estimate against exactly the
  template families the label might belong to.
* **Frame C -- the offline catalog text census.** All 1,475 committed catalog
  records, searched in committed fields only. Zero fetches, so it is reproducible
  forever, and it is a census rather than a sample.

Nothing here reaches the network. The live outcomes measured against these
frames are frozen in `evaluation/p7_residual.json`.

Usage::

    python tools/p7_frame.py                 # every frame and every offline census
    python tools/p7_frame.py --ids frame_r   # bare ids, for the live probe
    python tools/p7_frame.py --ids frame_s
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import subtopic_sources                                # noqa: E402
from scripts.extract_document_evidence import source_for_record     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "opportunities.js"
CENSUS = ROOT / "evaluation" / "attachment_census.jsonl"
EVIDENCE = ROOT / "data" / "document_evidence.json"

# --- Frame R -----------------------------------------------------------------
#
# Every entry names the committed artifact that observed the form, because §17.8
# forbids carrying a shape whose validating document cannot be quoted. `sample`
# says which draw the observation came from, and that matters: the census 20 was
# hand-picked and `docs/FAMILY_TAXONOMY.md` §4.2 forbids it entering any rate,
# so it contributes form *discovery* only.
#
# `form` uses the taxonomy's six-form vocabulary (§4 of FAMILY_TAXONOMY.md).
FORM_OBSERVATIONS: tuple[dict, ...] = (
    # F1 bare numbered -> Fm2. The eight records §18.3a names by id.
    {"id": "332894", "form": "F1", "sample": "census",   "n": 6,
     "source": "FAMILY_TAXONOMY.md §1 census 20 / TOPIC_LAYER_PLAN.md §18.3a",
     "marker": "1.) Spin qubits, fast."},
    {"id": "345938", "form": "F1", "sample": "survey",   "n": 8,
     "source": "COVERAGE_SURVEY.md stage 2 / §18.3a", "marker": "1)"},
    {"id": "361526", "form": "F1", "sample": "census",   "n": 21,
     "source": "FAMILY_TAXONOMY.md §1 / §18.3a", "marker": "challenge areas"},
    {"id": "360205", "form": "F1", "sample": "survey",   "n": 37,
     "source": "COVERAGE_SURVEY.md stage 2 / §18.3a", "marker": "1a."},
    {"id": "328902", "form": "F1", "sample": "taxonomy", "n": 7,
     "source": "FAMILY_TAXONOMY.md §4.1", "marker": "1."},
    {"id": "330175", "form": "F1", "sample": "taxonomy", "n": 24,
     "source": "FAMILY_TAXONOMY.md §4.1 / §2.1",
     "marker": "1. Aeronautics (Aeronautics Research Center)"},
    {"id": "355150", "form": "F1", "sample": "taxonomy", "n": 16,
     "source": "FAMILY_TAXONOMY.md §4.1", "marker": "1."},
    {"id": "362910", "form": "F1", "sample": "taxonomy", "n": 2,
     "source": "FAMILY_TAXONOMY.md §4.1 (borderline: funding pools)", "marker": "1."},

    # F4 named / bulleted -> Fm1. Nine in the 90 plus Cov7's 359782.
    {"id": "343653", "form": "F4", "sample": "census",   "n": 10,
     "source": "FAMILY_TAXONOMY.md §1 census 20 (category (c), depth-0 named set)",
     "marker": "ten country FOAs, bookmarked at outline depth 0"},
    {"id": "362329", "form": "F4", "sample": "census",   "n": None,
     "source": "FAMILY_TAXONOMY.md §1 census 20",
     "marker": "AUTOIMMUNE DISORDERS AND IMMUNOLOGY -> • Celiac Disease"},
    {"id": "362233", "form": "F4", "sample": "survey",   "n": 5,
     "source": "COVERAGE_SURVEY.md stage 2 / FAMILY_TAXONOMY.md §1",
     "marker": "five bulleted FY26 LRP IA Focus Areas"},
    {"id": "363000", "form": "F4", "sample": "survey",   "n": 3,
     "source": "COVERAGE_SURVEY.md stage 2", "marker": "bulleted project types"},
    {"id": "363607", "form": "F4", "sample": "survey",   "n": 6,
     "source": "COVERAGE_SURVEY.md stage 2 (one subdivision per attachment)",
     "marker": "Addenda G-L"},
    {"id": "vpr-email:vpr-aed7d81578b24028", "form": "F4", "sample": "survey", "n": 7,
     "source": "COVERAGE_SURVEY.md stage 2 / FAMILY_TAXONOMY.md §1",
     "marker": "seven named Sloan fellowship fields"},
    {"id": "362871", "form": "F4", "sample": "taxonomy", "n": 14,
     "source": "FAMILY_TAXONOMY.md §4.1",
     "marker": "• Artificial Intelligence and Autonomy"},
    {"id": "363578", "form": "F4", "sample": "taxonomy", "n": 3,
     "source": "FAMILY_TAXONOMY.md §4.1", "marker": "•"},
    {"id": "358716", "form": "F4", "sample": "taxonomy", "n": 2,
     "source": "FAMILY_TAXONOMY.md §4.1 (found on the agency page)",
     "marker": "Community Facilities / Economic Development"},
    {"id": "359782", "form": "F4", "sample": "cov7",     "n": 4,
     "source": "evaluation/cov7_stratum_d.json",
     "marker": "Design/Build/Buy · Surge and Sustain · Long Range Effects"},

    # F5 tabular -> Fm5. One observation in the whole corpus.
    {"id": "363530", "form": "F5", "sample": "taxonomy", "n": 12,
     "source": "FAMILY_TAXONOMY.md §4 / §4.1", "marker": "I.C.1 1 (table rows)"},

    # F3 coded named list -> Fm6.
    {"id": "361908", "form": "F3", "sample": "taxonomy", "n": 5,
     "source": "FAMILY_TAXONOMY.md §4.1", "marker": "PA 1: Seventh-generation greenhouses"},
    {"id": "352741", "form": "F3", "sample": "census",   "n": 32,
     "source": "FAMILY_TAXONOMY.md §1 census 20", "marker": "53-24-01 - HIGH FREQUENCY RADAR"},
    {"id": "362681", "form": "F3", "sample": "census",   "n": 39,
     "source": "FAMILY_TAXONOMY.md §1 census 20", "marker": "A.1.a."},
    {"id": "356612", "form": "F3", "sample": "census",   "n": 7,
     "source": "FAMILY_TAXONOMY.md §4.1", "marker": "Thrust Area 1, Topic A2:"},

    # Fm8 labelled ordinal. One observation, which is why P7.1 must size it.
    {"id": "363381", "form": "Fm8", "sample": "cov7", "n": 4,
     "source": "evaluation/cov7_stratum_d.json", "marker": "PRIORITY AREA 1-4"},
)

#: The three records P5's closeout makes required P7 false-positive fixtures.
FIXTURE_RECORDS: tuple[dict, ...] = (
    {"id": "360335", "surface": "cdc_components",
     "why": "Component 1-4 carry their own ceilings AND the `component` family "
            "matches them, yet the notice says applicants must apply for all "
            "components -- funding tranches, not alternatives"},
    {"id": "360334", "surface": "cdc_components",
     "why": "sibling notice, same shape"},
    {"id": "347414", "surface": "eda_investment_priorities",
     "why": "seven named priorities that 'are also evaluation factors', of which "
            "'each project must be consistent with #2' -- alignment criteria, "
            "not selectable subdivisions"},
)

# --- Frame S -----------------------------------------------------------------
FRAME_S_SEED = 20260820
FRAME_S_SIZE = 60

# --- Frame C ------------------------------------------------------------------
#
# The `Fm8` shape, narrow by construction. The observed form is `PRIORITY AREA 1`
# through `PRIORITY AREA 4` (Cov7, `363381`), so the pattern admits a case fold,
# an optional plural, and ordinary punctuation or spacing between the label and
# the integer -- and nothing else. It is deliberately NOT `<noun>\s+Area\s+N`:
# broadening it after seeing results is how a measurement is talked into a
# population it does not have (§17.8).
FM8_SHAPE = re.compile(
    r"priority\s+area(?:s)?\s*[#:.–—-]?\s*(\d{1,2})\b", re.IGNORECASE
)
#: The label without an ordinal. Reported separately, never as an Fm8 hit.
FM8_LABEL_ONLY = re.compile(r"priority\s+(?:program\s+)?areas?\b", re.IGNORECASE)
#: Committed catalog fields searched by Frame C, and the reason each is fair game:
#: `description` is the Grants.gov synopsis, `title` the record title, and
#: `document_search_text` the notice-derived fact quotes. None is full document
#: text, which is why Frame C bounds nothing on its own (see the report's note).
FRAME_C_FIELDS = ("title", "description", "document_search_text")


def load_catalog():
    raw = CATALOG.read_text(encoding="utf-8")
    payload = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    return payload


def load_attachment_census():
    census = {}
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            census[row["opportunity_id"]] = row.get("attachments") or []
    return census


def fetchable(attachments):
    """Exactly what `attachment_sources` would offer, without the network."""
    out = []
    for attachment in attachments:
        name = attachment.get("file_name") or ""
        if subtopic_sources._skippable(name):
            continue
        if subtopic_sources._is_html_stub(name, attachment.get("size_bytes")):
            continue
        out.append(attachment)
    return out[:subtopic_sources.MAX_ATTACHMENTS]


def has_text_surface(record, attachments):
    """Does production have *any* bytes it could read for this record?

    The union of the three surfaces production actually uses: the designated
    source (`source_for_record`), Cov1's agency-page fallback
    (`subtopic_only_primary`), and any fetchable Grants.gov attachment. The
    complement of this set over the catalog reproduces P5 clause 1's
    **314 unreachable records**, which is what licenses using it as an
    eligibility rule rather than inventing a new one.
    """
    return bool(
        source_for_record(record) is not None
        or subtopic_sources.subtopic_only_primary(record) is not None
        or fetchable(attachments)
    )


def frame_r():
    """The historical form-bearing census, plus the three required fixtures."""
    ids = []
    for row in FORM_OBSERVATIONS:
        if row["id"] not in ids:
            ids.append(row["id"])
    for row in FIXTURE_RECORDS:
        if row["id"] not in ids:
            ids.append(row["id"])
    return ids


def frame_s(catalog=None, census=None, *, exclude=None):
    """Seeded simple random sample of records with a fetchable text surface.

    Frame R is excluded so the two denominators can never be silently combined.
    """
    payload = catalog or load_catalog()
    census = census if census is not None else load_attachment_census()
    excluded = set(exclude if exclude is not None else frame_r())
    eligible = sorted(
        str(record["opportunity_id"])
        for record in payload["opportunities"]
        if str(record["opportunity_id"]) not in excluded
        and has_text_surface(record, census.get(str(record["opportunity_id"]), []))
    )
    drawn = random.Random(FRAME_S_SEED).sample(eligible, FRAME_S_SIZE)
    return sorted(drawn), len(eligible)


def frame_c_census(catalog=None):
    """Fm8's offline catalog text census. A census, and it fetches nothing."""
    payload = catalog or load_catalog()
    shape_hits, label_hits = {}, {}
    for record in payload["opportunities"]:
        rid = str(record["opportunity_id"])
        for field in FRAME_C_FIELDS:
            text = record.get(field) or ""
            found = sorted({m.group(1) for m in FM8_SHAPE.finditer(text)},
                           key=int)
            if found:
                shape_hits.setdefault(rid, {})[field] = found
            if FM8_LABEL_ONLY.search(text):
                label_hits.setdefault(rid, []).append(field)
    return {
        "records_searched": len(payload["opportunities"]),
        "fields": list(FRAME_C_FIELDS),
        "shape_hits": shape_hits,
        "label_only_hits": label_hits,
    }


def extraction_causes(catalog=None):
    """`no_extractable_text` and its neighbours, from the committed evidence cache.

    **This is a fact-extraction denominator, not a segmentation one.** The cache
    records what `extract_containers` produced for the one document
    `source_for_record` designated, so a zero here is the same *cause* the
    segmenter would hit on that document and is **not** the same *population* as
    the D5 backfill's 770 documents. Restricted to records still in the catalog,
    because **DEBT-4** (213 stale entries) inflates any cache-derived denominator.
    """
    payload = catalog or load_catalog()
    live = {str(r["opportunity_id"]) for r in payload["opportunities"]}
    entries = json.loads(EVIDENCE.read_text(encoding="utf-8"))["records"]
    causes = {
        "entries_in_cache": len(entries),
        "entries_for_live_records": 0,
        "status_current": 0,
        "status_failed_or_other": 0,
        "zero_characters": [],
        "under_500_characters": [],
        "by_content_kind": {},
        "failed_last_error_kinds": {},
    }
    for rid, entry in entries.items():
        if rid not in live:
            continue
        causes["entries_for_live_records"] += 1
        if entry.get("status") != "current":
            causes["status_failed_or_other"] += 1
            error = str(entry.get("last_error") or "unrecorded")
            key = error.split(":")[0][:60]
            causes["failed_last_error_kinds"][key] = (
                causes["failed_last_error_kinds"].get(key, 0) + 1
            )
            continue
        causes["status_current"] += 1
        extraction = entry.get("extraction") or {}
        kind = str(extraction.get("content_kind") or extraction.get("method") or "unknown")
        chars = extraction.get("text_characters")
        bucket = causes["by_content_kind"].setdefault(
            kind, {"documents": 0, "zero_characters": 0, "under_500": 0}
        )
        bucket["documents"] += 1
        if chars == 0:
            bucket["zero_characters"] += 1
            causes["zero_characters"].append(rid)
        elif isinstance(chars, int) and chars < 500:
            bucket["under_500"] += 1
            causes["under_500_characters"].append(rid)
    return causes


def reachability(catalog=None, census=None):
    payload = catalog or load_catalog()
    census = census if census is not None else load_attachment_census()
    reachable = unreachable = 0
    for record in payload["opportunities"]:
        rid = str(record["opportunity_id"])
        if has_text_surface(record, census.get(rid, [])):
            reachable += 1
        else:
            unreachable += 1
    return {"catalog": len(payload["opportunities"]),
            "reachable": reachable, "unreachable": unreachable}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", choices=("frame_r", "frame_s"),
                        help="print the frame's ids as JSON and exit")
    args = parser.parse_args()

    payload = load_catalog()
    census = load_attachment_census()

    if args.ids == "frame_r":
        print(json.dumps(frame_r()))
        return
    if args.ids == "frame_s":
        print(json.dumps(frame_s(payload, census)[0]))
        return

    catalog_ids = {str(r["opportunity_id"]) for r in payload["opportunities"]}
    print("P7.1 measurement frame -- enumerated offline, before any outcome")
    print(f"  catalog                                {len(catalog_ids):5}  "
          f"(data/opportunities.js, generated {payload['generated_at']})")
    reach = reachability(payload, census)
    print(f"  reachable text surface                 {reach['reachable']:5}")
    print(f"  unreachable under every current rule   {reach['unreachable']:5}"
          "   (P5 clause 1 measured 314)")
    print()

    ids_r = frame_r()
    absent = [i for i in ids_r if i not in catalog_ids]
    print(f"  Frame R -- historical form-bearing census  {len(ids_r):3} records"
          f"  ({len(FORM_OBSERVATIONS)} form observations + "
          f"{len(FIXTURE_RECORDS)} fixtures)")
    by_form = {}
    for row in FORM_OBSERVATIONS:
        by_form.setdefault(row["form"], []).append(row["id"])
    for form in ("F1", "F3", "F4", "F5", "Fm8"):
        rows = by_form.get(form, [])
        print(f"    {form:4} {len(rows):3} records  {' '.join(rows)}")
    print(f"    absent from the committed catalog: "
          f"{', '.join(absent) if absent else 'none'}")
    print()

    ids_s, eligible = frame_s(payload, census)
    print(f"  Frame S -- Fm8 document-surface sample     {len(ids_s):3} records"
          f"  of {eligible} eligible, seed {FRAME_S_SEED}, no agency cap")
    print("    " + " ".join(ids_s))
    print()

    frame_c = frame_c_census(payload)
    print(f"  Frame C -- offline catalog text census     "
          f"{frame_c['records_searched']} records, fields "
          f"{', '.join(frame_c['fields'])}")
    print(f"    records matching the Fm8 shape          "
          f"{len(frame_c['shape_hits'])}")
    for rid, fields in frame_c["shape_hits"].items():
        print(f"      {rid}  {fields}")
    print(f"    records carrying the label without an ordinal "
          f"{len(frame_c['label_only_hits'])}")
    print("      " + " ".join(sorted(frame_c["label_only_hits"])))
    print()

    causes = extraction_causes(payload)
    print("  Extraction causes, committed evidence cache restricted to the catalog")
    print(f"    cache entries                          {causes['entries_in_cache']:5}")
    print(f"    entries for live catalog records       "
          f"{causes['entries_for_live_records']:5}"
          "   (the rest is DEBT-4 residue)")
    print(f"    status current                         {causes['status_current']:5}")
    print(f"    status failed / other                  "
          f"{causes['status_failed_or_other']:5}  {causes['failed_last_error_kinds']}")
    print(f"    zero extractable characters            "
          f"{len(causes['zero_characters']):5}  {causes['zero_characters']}")
    print(f"    under 500 characters                   "
          f"{len(causes['under_500_characters']):5}")
    for kind, bucket in sorted(causes["by_content_kind"].items()):
        print(f"      {kind:12} documents {bucket['documents']:4}  "
              f"zero {bucket['zero_characters']:3}  under-500 {bucket['under_500']:3}")


if __name__ == "__main__":
    main()
