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

It is an evidence registry: extend PROGRAM_RULES to cover more agencies and
programs whose official scope is missing from the catalog record. Rules match
stable announcement numbers or tightly scoped record signals and cite the
official pages that support the added language. It runs in the merge step
(which rebuilds the search index), so no search-time ``is_broad`` escape hatch
is needed.
"""

from __future__ import annotations

from copy import deepcopy
import re


DISCOVERABILITY_REGISTRY_VERSION = "2026-08-15"


# A rule matches when a stable announcement number matches, any ``triggers``
# substring matches, or every ``triggers_all`` substring matches. Prefer an
# identifier or ``triggers_all`` for broad calls; a generic label such as
# "broad agency announcement" is deliberately insufficient by itself.
PROGRAM_RULES: list[dict] = [
    {
        "id": "nasa-spacetech-reddi-umbrella",
        "identifiers": ["NNH26ZTR001N"],
        "topics": [
            "Artificial intelligence and machine learning", "Data science",
            "Energy", "Manufacturing", "Materials science",
            "Space and aeronautics", "Technology development",
        ],
        "terms": [
            "space propulsion", "in-space propulsion", "flight computing",
            "avionics", "aerospace power", "energy storage",
            "robotic systems", "space robotics", "space communications",
            "space navigation", "orbital debris", "life support",
            "habitation systems", "in situ resource utilization",
            "sensors and instruments", "entry descent and landing",
            "autonomous systems", "artificial intelligence",
            "modeling and simulation", "information processing",
            "materials and structures", "mechanical systems",
            "advanced manufacturing", "surface systems",
            "thermal management", "flight vehicle systems",
            "air traffic management", "guidance navigation and control",
        ],
        "evidence_urls": [
            "https://www.nasa.gov/stmd-solicitations-and-opportunities/",
            "https://www.nasa.gov/otps/2024-nasa-technology-taxonomy/",
        ],
    },
    {
        "id": "army-research-lab-foundational-baa",
        "identifiers": ["W911NF-23-S-0001"],
        "topics": [
            "Artificial intelligence and machine learning",
            "Biology and biotechnology", "Cybersecurity", "Data science",
            "Energy", "Manufacturing", "Materials science",
            "Quantum science", "Social and behavioral sciences",
            "Technology development",
        ],
        "terms": [
            "synthetic biology", "biological materials",
            "electromagnetic spectrum", "radar", "electronic warfare",
            "power conversion", "energy storage", "directed energy",
            "human systems", "human autonomy", "autonomous systems",
            "artificial intelligence", "machine learning", "network science",
            "cybersecurity", "distributed computing", "photonics",
            "electronics", "quantum science", "quantum sensing",
            "extreme materials", "additive manufacturing",
            "energetic materials", "ballistics", "propulsion",
            "guidance navigation and control",
        ],
        "evidence_urls": [
            "https://arl.devcom.army.mil/collaborate-with-us/opportunity/arl-baa/",
            "https://arl.devcom.army.mil/what-we-do/",
        ],
    },
    {
        "id": "noaa-national-weather-service-baa",
        "identifiers": ["NOAA-NWS-2024-28059"],
        "topics": [
            "Climate change", "Data science", "Environmental science", "Water",
        ],
        "terms": [
            "meteorology", "weather forecasting", "hydrology",
            "climate services", "severe weather", "hurricanes", "floods",
            "drought", "weather observations", "weather radar",
            "impact-based decision support", "numerical weather prediction",
            "space weather",
        ],
        "evidence_urls": [
            "https://www.weather.gov/about/",
            "https://simpler.grants.gov/opportunity/d608e124-edb6-4788-85f1-65c924070f62",
        ],
    },
    {
        "id": "noaa-nesdis-star-baa",
        "identifiers": ["NOAA-NESDISPO-STAR-2024-27967"],
        "topics": [
            "Climate change", "Data science", "Environmental science",
            "Space and aeronautics",
        ],
        "terms": [
            "satellite remote sensing", "Earth observations",
            "environmental satellite data", "weather satellites",
            "climate data", "environmental monitoring", "data products",
            "satellite instruments", "atmospheric observations",
            "ocean observations", "space weather",
        ],
        "evidence_urls": [
            "https://www.nesdis.noaa.gov/about/our-mission",
            "https://www.star.nesdis.noaa.gov/star/STARMissionVision.php",
        ],
    },
    {
        "id": "noaa-oceanic-atmospheric-research-baa",
        "identifiers": ["NOAA-OAR-CPO-2024-28363"],
        "topics": [
            "Carbon management", "Climate change", "Data science",
            "Environmental science", "Water",
        ],
        "terms": [
            "climate research", "weather research", "ocean research",
            "atmospheric research", "air quality", "ocean acidification",
            "ocean observations", "Earth system modeling", "hurricanes",
            "tornadoes", "coastal ecosystems", "Great Lakes",
            "carbon cycle", "atmospheric chemistry", "forecasting",
        ],
        "evidence_urls": [
            "https://research.noaa.gov/",
            "https://research.noaa.gov/wp-content/uploads/2023/05/"
            "OAR-Strategy-2020-2026-14.pdf",
        ],
    },
    {
        "id": "noaa-fisheries-baa",
        "identifiers": ["NOAA-NMFS-FHQ-2024-27611"],
        "topics": [
            "Agriculture and food", "Biology and biotechnology",
            "Climate change", "Environmental science", "Water",
        ],
        "terms": [
            "fisheries science", "sustainable fisheries",
            "fisheries management", "seafood", "aquaculture",
            "fish stock assessment", "marine ecosystems",
            "protected species", "marine mammals", "habitat conservation",
            "bycatch", "coastal communities", "ocean resources",
            "living marine resources", "climate-ready fisheries",
        ],
        "evidence_urls": [
            "https://www.fisheries.noaa.gov/grant/"
            "fiscal-year-2024-2026-broad-agency-announcement",
            "https://www.fisheries.noaa.gov/about-us",
        ],
    },
    {
        "id": "noaa-office-education-baa",
        "identifiers": ["NOAA-SEC-OED-2024-28060"],
        "topics": [
            "Climate change", "Education and workforce",
            "Environmental science", "Water",
        ],
        "terms": [
            "STEM education", "environmental literacy",
            "teaching and learning", "ocean education", "coastal education",
            "climate education", "weather education", "workforce development",
            "career pathways", "student education", "community resilience",
            "environmental hazards",
        ],
        "evidence_urls": [
            "https://www.noaa.gov/office-education/noaa-education-council/"
            "strategic-planning",
            "https://simpler.grants.gov/opportunity/"
            "a41c508c-e2c8-48bd-be6d-615027fca6b7",
        ],
    },
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
        "evidence_urls": [
            "https://science.osti.gov/grants/FOAs/FOAs/2026/DE-FOA-0003600",
            "https://science.osti.gov/bes/Research",
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
        "evidence_urls": [
            "https://science.osti.gov/bes/Research",
            "https://science.osti.gov/bes/csgb/Research-Areas/Catalysis-Science",
        ],
    },
    {
        "id": "doe-energy-efficiency-renewable",
        "triggers": [
            "energy efficiency and renewable energy",
            "advanced manufacturing office", "industrial efficiency",
        ],
        "trigger_tokens": ["eere"],
        "topics": ["Energy", "Manufacturing", "Carbon management", "Climate change"],
        "terms": [
            "renewable energy", "solar", "wind", "hydrogen", "energy storage",
            "bioenergy", "advanced manufacturing", "industrial decarbonization",
            "grid", "vehicle technologies",
        ],
        "evidence_urls": [
            "https://eere-exchange.energy.gov/",
            "https://www.energy.gov/industrial-technologies/"
            "industrial-technology-programs-across-us-department-energy",
        ],
    },
    {
        "id": "onr-long-range-baa",
        "identifiers": ["N0001425SB001"],
        "triggers_all": [
            "office of naval research",
            "long range broad agency announcement",
        ],
        "topics": [
            "Catalysis and reaction engineering", "Materials science",
            "Separations and membranes", "Energy",
            "Artificial intelligence and machine learning", "Quantum science",
        ],
        "terms": [
            "catalysis", "catalyst design", "electrochemistry",
            "electrochemical reaction pathways", "sorbents", "membranes",
            "critical materials", "selective extraction", "chemical separation",
            "materials science", "artificial intelligence", "machine learning",
            "autonomous systems", "quantum science", "quantum sensing",
            "photonics", "power and energy", "thermal management",
        ],
        "evidence_urls": [
            "https://www.onr.navy.mil/organization/departments/code-33/"
            "materials-focus-area/materials-treatment-and-recovery",
            "https://www.onr.navy.mil/organization/departments/code-33/"
            "power-and-energy-focus-area/fuel-flexibility-contingency",
            "https://www.onr.navy.mil/organization/departments/code-33/"
            "materials-focus-area/artificial-intelligence-machine-learning",
            "https://www.onr.navy.mil/organization/departments/code-31/"
            "division-311/atomic-molecular-and-quantum-physics",
        ],
    },
]

_TEXT_FIELDS = ("agency", "opportunity_number", "title", "description")


def _record_text(record: dict) -> str:
    return " ".join(
        str(record.get(field) or "") for field in _TEXT_FIELDS
    ).casefold()


def _rule_matches(rule: dict, record: dict, text: str) -> bool:
    number = str(record.get("opportunity_number") or "").strip().casefold()
    identifiers = {
        str(value).strip().casefold()
        for value in rule.get("identifiers", [])
        if str(value).strip()
    }
    if number and number in identifiers:
        return True

    triggers = [str(value).casefold() for value in rule.get("triggers", [])]
    if triggers and any(trigger in text for trigger in triggers):
        return True

    trigger_tokens = {
        str(value).strip().casefold()
        for value in rule.get("trigger_tokens", [])
        if str(value).strip()
    }
    if trigger_tokens:
        record_tokens = set(re.findall(r"[a-z0-9]+", text))
        if trigger_tokens & record_tokens:
            return True

    triggers_all = [
        str(value).casefold() for value in rule.get("triggers_all", [])
    ]
    return bool(triggers_all) and all(trigger in text for trigger in triggers_all)


def matching_rules(record: dict) -> list[dict]:
    """Return the registry rules whose scoped signals match ``record``."""
    text = _record_text(record)
    return [
        rule for rule in PROGRAM_RULES
        if _rule_matches(rule, record, text)
    ]


def supplemental(record: dict) -> tuple[list[str], list[str]]:
    """Return (topics_to_add, terms_to_add) for a single record."""
    topics: list[str] = []
    terms: list[str] = []
    for rule in matching_rules(record):
        topics.extend(rule.get("topics", []))
        terms.extend(rule.get("terms", []))
    return topics, terms


def augment_records(records: list[dict]) -> int:
    """Attach program-area topics/terms in place. Returns how many were changed.

    Topics are appended to ``topic_areas`` (indexed and shown as a facet); terms
    are appended to ``document_search_text`` (indexed only). Both are de-duped
    and existing values are preserved.
    """
    registered_rule_ids = {rule["id"] for rule in PROGRAM_RULES}
    changed = 0
    for record in records:
        before = deepcopy(record)

        # Remove the prior registry-owned contribution before reevaluating the
        # current rules. This makes rule corrections and retirement reversible
        # while preserving source/extractor text and topics.
        previous = record.pop("discoverability_contribution", None)
        if isinstance(previous, dict):
            addition = str(previous.get("document_search_addition") or "").strip()
            existing_text = str(record.get("document_search_text") or "").strip()
            if addition and existing_text == addition:
                record["document_search_text"] = ""
            elif addition and existing_text.endswith(f" {addition}"):
                record["document_search_text"] = existing_text[:-(len(addition) + 1)]

            added_topics = set(previous.get("topic_areas_added") or [])
            if added_topics:
                record["topic_areas"] = [
                    topic for topic in (record.get("topic_areas") or [])
                    if topic not in added_topics
                ]

        rules = matching_rules(record)
        topics = [topic for rule in rules for topic in rule.get("topics", [])]
        terms = [term for rule in rules for term in rule.get("terms", [])]

        existing_topics = list(record.get("topic_areas") or [])
        merged_topics = list(dict.fromkeys(existing_topics + topics))
        added_topics = [
            topic for topic in merged_topics if topic not in existing_topics
        ]
        if added_topics:
            record["topic_areas"] = merged_topics

        addition = ""
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

        retained_evidence = [
            item
            for item in (record.get("discoverability_evidence") or [])
            if not (
                isinstance(item, dict)
                and item.get("rule_id") in registered_rule_ids
            )
        ]
        evidence_by_rule = {
            str(item.get("rule_id")): item
            for item in retained_evidence
            if isinstance(item, dict) and item.get("rule_id")
        }
        for rule in rules:
            evidence_by_rule[rule["id"]] = {
                "rule_id": rule["id"],
                "official_urls": list(rule.get("evidence_urls") or []),
            }
        merged_evidence = [
            evidence_by_rule[key] for key in sorted(evidence_by_rule)
        ]
        if merged_evidence:
            record["discoverability_evidence"] = merged_evidence
        else:
            record.pop("discoverability_evidence", None)

        if rules:
            record["discoverability_registry_version"] = DISCOVERABILITY_REGISTRY_VERSION
            record["discoverability_augmented"] = True
            record["discoverability_contribution"] = {
                "rule_ids": sorted(rule["id"] for rule in rules),
                "topic_areas_added": added_topics,
                "document_search_addition": addition,
            }
        elif isinstance(previous, dict):
            record.pop("discoverability_registry_version", None)
            record.pop("discoverability_augmented", None)

        if record != before:
            changed += 1
    return changed
