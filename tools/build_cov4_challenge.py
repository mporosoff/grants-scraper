"""Build the Cov4 challenge set — Population B — with truth labels committed first.

Usage: python tools/build_cov4_challenge.py [--out evaluation/cov4_challenge.json]

**Why a second artifact.** The frozen MEAS-3 population (`meas3_population.json`) is
what production actually emits today, and it is **overwhelmingly positive** — it
contains no scored contaminants, so it cannot measure false accepts at all. This set
exists to exercise Cov4's semantic boundary in both directions.

**MEAS-3 is immutable.** Nothing here modifies its population, prompt, raw outputs,
decision table or reported result. Candidates re-used from it are *copied*, and the
copy records where it came from.

**Every candidate is real document text**, quoted from documents this project has
already fetched and read, with a page cite and a truth label whose evidence is stated
inline. Nothing is invented, and **no label comes from a classifier** — that would be
grading a model against itself.

**This does not implement F1 or F4 recognisers and does not start P7.** The F1 and F4
entries are *evaluation candidates*, hand-extracted from documents already read, to
answer one question: *if P7 later produces one of these spans, can Cov4 tell the
genuine child from the look-alike?* Evaluation candidates are not production
candidates.

Truth vocabulary, deliberately three-valued:

* ``fundable``   — a genuine program/topic/research subdivision under the umbrella
                   that an applicant can propose work against;
* ``contaminant``— administrative, procedural, organizational, review-criteria,
                   navigation, or belonging to a different opportunity;
* ``unresolved`` — genuinely undecided by a human; **excluded from scoring**, never
                   forced to a binary (DEC-11 is the worked example).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_OUT = Path("evaluation/cov4_challenge.json")
MEAS3 = Path("evaluation/meas3_population.json")

#: Candidates copied from the frozen MEAS-3 population, with the human truth label
#: and the evidence for it. The four stable false negatives and the unstable span are
#: all here by name, because they are the cases the next prompt must fix.
FROM_MEAS3 = {
    # --- the four stable false negatives (MEAS-3 §4a.2) --------------------
    "360678:amr": ("fundable", "BER programme in DE-FOA-0003600's own program list; "
                   "docs/CORPUS_CENSUS.md records 68 of 71 programmes as correct"),
    "360678:bhinp": ("fundable", "NP subprogram in the FOA's program list (census)"),
    "360678:dfs": ("fundable", "NP subprogram in the FOA's program list (census)"),
    "361526:suslidc-10": ("fundable", "one of the 21 Genesis Mission challenge areas "
                          "the census verified as 'exactly the published list'"),
    # --- the unstable span -------------------------------------------------
    "360678:ixrs": ("fundable", "BES programme; census records (i) X-Ray Scattering "
                    "at level 2 of the program taxonomy"),
    # --- DEC-11: preserved as unresolved, never labelled opportunistically --
    "360678:nppp": ("unresolved", "DEC-11 is open: is Public-Private Partnerships a "
                    "subject an applicant applies against, or a mechanism through "
                    "which any subject may be funded? A human must settle it, and "
                    "not from a model verdict"),
    # --- stable-accept positives, spread across all four accepting records --
    "360678:qcs": ("fundable", "(q) Catalysis Science — the case §6.7 was written "
                   "around; census locates it at level 2, page 46"),
    "360678:aam": ("fundable", "(a) Applied Mathematics, ASCR programme (census)"),
    "360678:rss": ("fundable", "(r) Separation Science, BES programme (census)"),
    "360678:tg": ("fundable", "(t) Geosciences, BES programme (census)"),
    "360678:vps": ("fundable", "(v) Photosynthetic Systems, BES programme (census)"),
    "360678:jns": ("fundable", "(j) Neutron Scattering, BES programme (census)"),
    "361526:ramaip-1": ("fundable", "Genesis Mission challenge area 1 (census: 21 of 21)"),
    "361526:stbr-2": ("fundable", "Genesis Mission challenge area 2 (census)"),
    "361526:adofe-5": ("fundable", "Genesis Mission challenge area 5 (census)"),
    "363526:t-1": ("fundable", "AFOSR DEPSCoR Topic 1; the corpus's only high-confidence "
                  "acceptance, 12 of 12 topics correct (census)"),
    "363526:t-3": ("fundable", "AFOSR DEPSCoR Topic 3 (census)"),
    "356623:c-1": ("fundable", "ARPA-E SCALEUP CATEGORY 1; taxonomy records 7 of 7 "
                   "correct via technical_category"),
    "356623:c-6": ("fundable", "ARPA-E SCALEUP CATEGORY 6 (taxonomy)"),
}

#: Hand-extracted real-document candidates. Every `excerpt` is quoted text from a
#: document already fetched and verified by digest in this project; `page` is where
#: it sits. These are the negatives and the F1/F4 shapes the production path does not
#: currently emit.
HAND_BUILT = [
    # ---------------- administrative / procedural contaminants -------------
    {
        "candidate_id": "360678:x-multi-institutional-teams",
        "parent_opportunity_id": "360678",
        "shape": "administrative_heading",
        "title": "Multi-Institutional Teams",
        "excerpt": "Applicants proposing a multi-institutional team must follow the "
                   "instructions in Section IV for a Title Page Supplement for "
                   "Multi-Institutional Teams, including the required table.",
        "page": 118,
        "truth_label": "contaminant",
        "truth_evidence": "An application-format instruction, not a research subject. "
                          "docs/CORPUS_CENSUS.md lists it as one of 360678's two "
                          "contaminating spans in the pre-Cov5 run",
    },
    {
        "candidate_id": "361526:x-teaming-arrangements",
        "parent_opportunity_id": "361526",
        "shape": "eligibility_policy_prose",
        "title": "Teaming Arrangements",
        "excerpt": "Phase I: Small teams attack a particular challenge focus area or "
                   "part of a focus area. All teams in Phase I must include "
                   "institutions from at least two of the following categories: (1) "
                   "DOE/NNSA National Laboratory, (2) Industry, and (3) "
                   "IHE/Non-profit/Other.",
        "page": 60,
        "truth_label": "contaminant",
        "truth_evidence": "Eligibility/teaming policy. Census lists it among "
                          "361526's five spurious administrative spans",
    },
    {
        "candidate_id": "361526:x-annual-progress-reports",
        "parent_opportunity_id": "361526",
        "shape": "administrative_heading",
        "title": "Annual Progress Reports",
        "excerpt": "The lead institution shall submit an annual progress report on "
                   "behalf of the multi-institutional team.",
        "page": 60,
        "truth_label": "contaminant",
        "truth_evidence": "Post-award reporting requirement; census lists it among "
                          "361526's five spurious spans",
    },
    {
        "candidate_id": "360678:x-open-science",
        "parent_opportunity_id": "360678",
        "shape": "policy_prose",
        "title": "Open Science",
        "excerpt": "The Department is committed to open science and expects awardees "
                   "to make publications and digital data resulting from federally "
                   "funded research publicly accessible in accordance with the "
                   "Department's public access plan.",
        "page": 120,
        "truth_label": "contaminant",
        "truth_evidence": "A policy commitment applying to all awards; census lists "
                          "it as one of 360678's two contaminating spans",
    },
    # ---------------- F4: named/bulleted, genuine vs adjacent decoys -------
    {
        "candidate_id": "362233:f4-focus-heterogeneity",
        "parent_opportunity_id": "362233",
        "shape": "f4_named_bulleted",
        "title": "Understanding how lupus disease heterogeneity impacts risk of disease",
        "excerpt": "Understanding how lupus disease heterogeneity impacts risk of "
                   "disease, disease presentation, clinical course and outcomes using "
                   "a diverse range of research disciplines including, but not limited "
                   "to, biopsychosocial studies, personalized medicine, variation in "
                   "treatment studies, health economics, socioeconomic studies, "
                   "environmental studies, systems biology, maternal fetal health and "
                   "epidemiological studies.",
        "page": 6,
        "truth_label": "fundable",
        "truth_evidence": "Listed under '3.2.1. Focus Areas for the IA — The proposed "
                          "research must address at least one of the following FY26 "
                          "LRP IA Focus Areas'. Applicants must address one",
    },
    {
        "candidate_id": "362233:f4-focus-mechanisms",
        "parent_opportunity_id": "362233",
        "shape": "f4_named_bulleted",
        "title": "Understanding the biological mechanisms of lupus disease",
        "excerpt": "Understanding the biological mechanisms of lupus disease "
                   "including, but not limited to, studies of informative/rare "
                   "patients.",
        "page": 7,
        "truth_label": "fundable",
        "truth_evidence": "Same 'must address at least one' Focus Areas list",
    },
    {
        "candidate_id": "362233:f4-focus-pathobiology",
        "parent_opportunity_id": "362233",
        "shape": "f4_named_bulleted",
        "title": "Determining the pathobiology of end organ injury related to lupus",
        "excerpt": "Determining the pathobiology of end organ injury related to lupus "
                   "disease in target human tissues.",
        "page": 7,
        "truth_label": "fundable",
        "truth_evidence": "Same 'must address at least one' Focus Areas list",
    },
    {
        "candidate_id": "362233:f4-decoy-innovation",
        "parent_opportunity_id": "362233",
        "shape": "f4_adjacent_decoy",
        "title": "Innovation",
        "excerpt": "Innovation: Innovative research may introduce a new paradigm, look "
                   "at existing problems from new perspectives or exhibit other highly "
                   "creative qualities. It is the responsibility of the PI to clearly "
                   "describe the innovation.",
        "page": 8,
        "truth_label": "contaminant",
        "truth_evidence": "A **review criterion**, not a research subject. This is the "
                          "adjacent-decoy case docs/FAMILY_TAXONOMY.md names for "
                          "362233: real Focus Areas sit one subsection above decoys",
    },
    {
        "candidate_id": "362233:f4-decoy-innovation-statement",
        "parent_opportunity_id": "362233",
        "shape": "f4_adjacent_decoy",
        "title": "Innovation Statement",
        "excerpt": "Innovation Statement – Attachment 6, upload as “Innovation.pdf”",
        "page": 21,
        "truth_label": "contaminant",
        "truth_evidence": "An application-contents checklist item naming a required "
                          "upload; quoted from the attachment checklist",
    },
    {
        "candidate_id": "362233:f4-decoy-statement-of-work",
        "parent_opportunity_id": "362233",
        "shape": "f4_adjacent_decoy",
        "title": "Statement of Work",
        "excerpt": "Statement of Work – Attachment 5, upload as “SOW.pdf”",
        "page": 21,
        "truth_label": "contaminant",
        "truth_evidence": "Application-contents checklist item",
    },
    # ---------------- F1: bare-numbered, genuine vs look-alikes -----------
    {
        "candidate_id": "330175:f1-aeronautics-arc",
        "parent_opportunity_id": "330175",
        "shape": "f1_bare_numbered",
        "title": "1. Aeronautics (Aeronautics Research Center)",
        "excerpt": "Aeronautics (Aeronautics Research Center). The Aeronautics "
                   "Research Center conducts research in aeronautical engineering and "
                   "related disciplines, and seeks proposals and white papers in those "
                   "areas under this BAA.",
        "page": 4,
        "truth_label": "fundable",
        "truth_evidence": "One of the USAFA BAA's research centers under 'a. Research "
                          "Centers'; §6.4a records 330175 as enumerating 24 real "
                          "subdivisions in three groups with restarting counters",
    },
    {
        "candidate_id": "330175:f1-chemistry",
        "parent_opportunity_id": "330175",
        "shape": "f1_bare_numbered",
        "title": "6. Chemistry (Chemistry Research Center)",
        "excerpt": "Chemistry (Chemistry Research Center). The Chemistry Research "
                   "Center solicits research in chemistry and related areas under this "
                   "Broad Agency Announcement.",
        "page": 8,
        "truth_label": "fundable",
        "truth_evidence": "Same 'a. Research Centers' enumeration",
    },
    {
        "candidate_id": "330175:f1-decoy-reserved",
        "parent_opportunity_id": "330175",
        "shape": "f1_bare_numbered_decoy",
        "title": "3. Reserved",
        "excerpt": "3. Reserved",
        "page": 6,
        "truth_label": "contaminant",
        "truth_evidence": "A placeholder in the numbered sequence. Quoted verbatim "
                          "from the document's own numbering; nothing is fundable here",
    },
    {
        "candidate_id": "330175:f1-decoy-toc",
        "parent_opportunity_id": "330175",
        "shape": "navigation_toc",
        "title": "I. OPPORTUNITY DESCRIPTION",
        "excerpt": "Table of Contents  I. OPPORTUNITY DESCRIPTION "
                   "....................................... 4  a. Research Centers "
                   "..................................... 4",
        "page": 3,
        "truth_label": "contaminant",
        "truth_evidence": "Table-of-contents navigation, the exact look-alike §6.4 "
                          "rule 6 exists to reject",
    },
    # ---------------- organizational / other-opportunity contaminants -----
    {
        "candidate_id": "363594:x-other-foa-topic",
        "parent_opportunity_id": "363594",
        "shape": "aggregating_agency_page",
        "title": "Topic Area 1: Improved Oil and Gas Recovery",
        "excerpt": "Topic Area 1: Improved Oil and Gas Recovery — an area of interest "
                   "under DE-FOA-0003627, listed among many open NETL funding "
                   "opportunities on this page.",
        "page": None,
        "truth_label": "contaminant",
        "truth_evidence": "BUG-9 / docs/FAMILY_TAXONOMY.md §4.6: on NETL's aggregating "
                          "landing page, topic_area fires 10 times and every topic "
                          "belongs to a *different* opportunity (DE-FOA-0003634, "
                          "DE-FOA-0003627), not to DE-FOA-0003215",
    },
    {
        "candidate_id": "360678:x-org-office-of-science",
        "parent_opportunity_id": "360678",
        "shape": "organizational_heading",
        "title": "Office of Science",
        "excerpt": "The Office of Science is the lead federal agency supporting "
                   "fundamental scientific research for energy and the Nation's "
                   "largest supporter of basic research in the physical sciences.",
        "page": 5,
        "truth_label": "contaminant",
        "truth_evidence": "The awarding organization itself, one level above any "
                          "programme; organizational, not a subdivision to apply to",
    },
    {
        "candidate_id": "360678:x-org-bes",
        "parent_opportunity_id": "360678",
        "shape": "organizational_heading",
        "title": "Basic Energy Sciences (BES)",
        "excerpt": "Basic Energy Sciences (BES) supports fundamental research to "
                   "understand, predict, and ultimately control matter and energy at "
                   "the electronic, atomic, and molecular levels.",
        "page": 40,
        "truth_label": "contaminant",
        "truth_evidence": "A **program office**, the parent of the (a)–(x) programmes. "
                          "Census: grouping by level-0 ancestor separates the 93-node "
                          "taxonomy from its office headings; the fundable unit is the "
                          "programme beneath, which is why this is the hardest negative "
                          "in the set",
    },
]


def build(out_path=DEFAULT_OUT):
    meas3 = json.loads(MEAS3.read_text(encoding="utf-8"))
    by_id = {c["candidate_id"]: c for c in meas3["candidates"]}
    rows = []
    for candidate_id, (label, evidence) in FROM_MEAS3.items():
        source = by_id.get(candidate_id)
        if source is None:
            raise SystemExit(f"{candidate_id} is not in the frozen MEAS-3 population")
        rows.append({
            "candidate_id": candidate_id,
            "origin": "meas3_population",
            "shape": "production_span",
            "parent_opportunity_id": source["parent_opportunity_id"],
            "parent_opportunity_number": source["parent_opportunity_number"],
            "parent_title": source["parent_title"],
            "subtopic_code": source["subtopic_code"],
            "title": source["title"],
            "excerpt": source["excerpt"],
            "page": source["page_start"],
            "truth_label": label,
            "truth_evidence": evidence,
        })
    meas3_parents = {c["parent_opportunity_id"]: c for c in meas3["candidates"]}
    for entry in HAND_BUILT:
        parent = meas3_parents.get(entry["parent_opportunity_id"])
        rows.append({
            "candidate_id": entry["candidate_id"],
            "origin": "hand_extracted_real_document",
            "shape": entry["shape"],
            "parent_opportunity_id": entry["parent_opportunity_id"],
            "parent_opportunity_number": (parent or {}).get(
                "parent_opportunity_number"),
            "parent_title": (parent or {}).get("parent_title"),
            "subtopic_code": entry["title"],
            "title": entry["title"],
            "excerpt": entry["excerpt"],
            "page": entry["page"],
            "truth_label": entry["truth_label"],
            "truth_evidence": entry["truth_evidence"],
        })
    rows.sort(key=lambda row: (row["parent_opportunity_id"], row["candidate_id"]))
    counts = {}
    for row in rows:
        counts[row["truth_label"]] = counts.get(row["truth_label"], 0) + 1
    payload = {
        "schema_version": 1,
        "purpose": "Cov4 challenge set (Population B) — balanced, real-document, "
                   "human-labelled before any classifier run",
        "relationship_to_meas3": (
            "MEAS-3 is immutable. Candidates marked origin=meas3_population are "
            "COPIES of frozen MEAS-3 rows; nothing in meas3_population.json, its "
            "prompt, its raw outputs or its decision table is modified."
        ),
        "labels_are_human": (
            "Every truth_label was assigned from document evidence cited in "
            "truth_evidence, before any prompt variant was run. No label derives "
            "from classifier output."
        ),
        "not_a_recogniser": (
            "The f1_* and f4_* rows are hand-extracted evaluation candidates from "
            "documents already read. They do not implement an F1 or F4 recogniser "
            "and do not start P7."
        ),
        "label_counts": counts,
        "candidate_count": len(rows),
        "candidates": rows,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    payload = build(args.out)
    print(f"wrote {args.out}: {payload['candidate_count']} candidates "
          f"{payload['label_counts']}")
    shapes = {}
    for row in payload["candidates"]:
        key = (row["shape"], row["truth_label"])
        shapes[key] = shapes.get(key, 0) + 1
    for (shape, label), count in sorted(shapes.items()):
        print(f"  {shape:28} {label:12} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
