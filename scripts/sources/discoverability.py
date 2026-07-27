"""Discoverability enrichment for opaque "umbrella" funding announcements.

Some agencies bundle many program areas into one broad announcement whose
Grants.gov text is generic. The clearest example: DOE Office of Science posts a
single "Continuation of Solicitation for the Office of Science Financial
Assistance Program" (DE-FOA-0003600) that actually funds Basic Energy Sciences
(catalysis, materials, chemistry, ...), Advanced Scientific Computing, Fusion,
etc. -- but its catalog text never says "catalysis," so a keyword search for
"catalysis" can't find it.

This module attaches program-area **topic tags** and **searchable terms** to
records that match a known program signal, so a topical search surfaces the
umbrella FOA and it appears under the right Topic facet. The added topics are
inferred (the same class as the pipeline's derived topic_areas) -- they are
searchable/facet signals, never presented as official FOA requirements.

It is a lexicon: extend PROGRAM_RULES to cover more agencies/programs. It runs
in the merge step (which rebuilds the search index), so no other file changes.
"""

from __future__ import annotations


# Each rule: if any trigger substring appears in a record's combined
# agency/number/title/description text, add these topic tags and search terms.
PROGRAM_RULES: list[dict] = [
    {
        "id": "doe-office-of-science-umbrella",
        "triggers": [
            "office of science financial assistance",
            "de-foa-0003600",
        ],
        "topics": [
            "Catalysis and reaction engineering", "Materials science",
            "Separations and membranes", "Carbon management", "Quantum science",
            "Energy", "Climate change", "Environmental science",
            "Biology and biotechnology", "Data science",
            "Artificial intelligence and machine learning",
        ],
        "terms": [
            "basic energy sciences", "catalysis", "chemical sciences", "chemistry",
            "materials science", "condensed matter physics", "separations",
            "electrochemistry", "photochemistry", "combustion", "geosciences",
            "advanced scientific computing", "applied mathematics",
            "biological and environmental research", "fusion energy sciences",
            "plasma physics", "high energy physics", "nuclear physics", "isotopes",
        ],
    },
    {
        "id": "doe-basic-energy-sciences",
        "triggers": ["basic energy sciences"],
        "topics": [
            "Catalysis and reaction engineering", "Materials science",
            "Separations and membranes", "Carbon management",
        ],
        "terms": [
            "catalysis", "chemical sciences", "chemistry", "materials science",
            "condensed matter physics", "separations", "electrochemistry",
            "photochemistry", "combustion",
        ],
    },
    {
        "id": "doe-energy-efficiency-renewable",
        "triggers": [
            "energy efficiency and renewable energy", "eere",
            "advanced manufacturing office", "industrial efficiency",
        ],
        "topics": ["Energy", "Manufacturing", "Carbon management", "Climate change"],
        "terms": [
            "renewable energy", "solar", "wind", "hydrogen", "energy storage",
            "bioenergy", "advanced manufacturing", "industrial decarbonization",
            "grid", "vehicle technologies",
        ],
    },
]

_TEXT_FIELDS = ("agency", "opportunity_number", "title", "description")


def _record_text(record: dict) -> str:
    return " ".join(
        str(record.get(field) or "") for field in _TEXT_FIELDS
    ).casefold()


def supplemental(record: dict) -> tuple[list[str], list[str]]:
    """Return (topics_to_add, terms_to_add) for a single record."""
    text = _record_text(record)
    topics: list[str] = []
    terms: list[str] = []
    for rule in PROGRAM_RULES:
        if any(trigger in text for trigger in rule["triggers"]):
            topics.extend(rule.get("topics", []))
            terms.extend(rule.get("terms", []))
    return topics, terms


def augment_records(records: list[dict]) -> int:
    """Attach program-area topics/terms in place. Returns how many were changed.

    Topics are appended to ``topic_areas`` (indexed and shown as a facet); terms
    are appended to ``document_search_text`` (indexed only). Both are de-duped
    and existing values are preserved.
    """
    changed = 0
    for record in records:
        topics, terms = supplemental(record)
        if not topics and not terms:
            continue
        touched = False

        existing_topics = list(record.get("topic_areas") or [])
        merged_topics = list(dict.fromkeys(existing_topics + topics))
        if merged_topics != existing_topics:
            record["topic_areas"] = merged_topics
            touched = True

        if terms:
            existing_text = str(record.get("document_search_text") or "").strip()
            existing_folded = existing_text.casefold()
            missing_terms = [
                term
                for term in dict.fromkeys(terms)
                if term.casefold() not in existing_folded
            ]
            if missing_terms:
                addition = " ".join(missing_terms)
                record["document_search_text"] = (
                    f"{existing_text} {addition}".strip()
                    if existing_text else addition
                )
                touched = True

        if touched:
            record["discoverability_augmented"] = True
            changed += 1
    return changed
