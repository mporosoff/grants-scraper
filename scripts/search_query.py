"""Conservative query expansion shared by server-side catalog search tools.

The browser equivalent lives in ``assets/search-query.js``. Keep the alias
keys and phrases synchronized; tests exercise the important contract on both
sides. Aliases are query-only so a catalog refresh is not required when the
glossary improves.
"""

from __future__ import annotations

import re

from .build_catalog import tokenize


PFAS_CONCEPT = (
    "persistent contaminant contamination pollution remediation groundwater "
    "drinking wastewater water treatment purification"
)
RARE_EARTH_CONCEPT = "ree rare earth element lanthanide scandium yttrium"
RARE_EARTH_EVIDENCE = (
    ("ree",),
    ("rare", "earth"),
    ("lanthanide",),
    ("scandium",),
    ("yttrium",),
)
IONIC_LIQUID_CONCEPT = (
    "ionic liquid solvent extraction separation membrane hydrometallurgy leaching"
)
IONIC_LIQUID_EVIDENCE = (
    ("ionic", "liquid"),
    ("solvent", "extraction"),
    ("solvent", "separation"),
    ("chemical", "separation"),
    ("desalination", "purification"),
    ("hydrometallurgy", "leaching"),
    ("ion", "exchange"),
)
BROAD_CALL_CONCEPT = "broad agency announcement baa long range office wide open scope"
BROAD_CALL_EVIDENCE = (
    ("broad", "agency", "announcement"),
    ("baa",),
    ("long", "range"),
    ("office", "wide"),
    ("open", "scope"),
)
BASIC_ENERGY_SCIENCES_CONCEPT = "basic energy science bes"
BASIC_ENERGY_SCIENCES_EVIDENCE = (
    ("basic", "energy", "science"),
    ("bes",),
)
CATALYSIS_CONCEPT = (
    "catalyst catalysis catalytic electrocatalysis photocatalysis thermocatalysis"
)
CATALYSIS_EVIDENCE = (
    ("catalysi",),
    ("catalytic",),
    ("electrocatalysi",),
    ("photocatalysi",),
    ("thermocatalysi",),
)
CATALYST_CONTEXT_WINDOWS = tuple(
    {"terms": ("catalyst", term), "maximum_span": 6}
    for term in (
        "chemical", "reaction", "reactor", "electrochemical", "heterogeneous",
        "homogeneous", "synthesis", "enzyme", "design", "characterization",
    )
)
AI_CONCEPT = "ai artificial intelligence machine learning"
AI_EVIDENCE = (
    ("ai",),
    ("artificial", "intelligence"),
    ("machine", "learn"),
)

QUERY_ALIASES: dict[str, str] = {
    "co2": "carbon dioxide",
    "ccs": "carbon capture",
    "ccus": "carbon capture",
    "ghg": "greenhouse",
    "h2": "hydrogen",
    "ch4": "methane",
    "n2o": "nitrous nitrogen",
    "nox": "nitrogen",
    "sox": "sulfur",
    "pm2.5": "particulate",
    "voc": "volatile organic",
    "dac": "air capture",
    "ldes": "energy storage",
    "pv": "photovoltaic",
    "ev": "electric vehicle",
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "llm": "generative",
    "hpc": "computing",
    "iot": "internet",
    "gis": "geographic geospatial",
    "uav": "aerial drone",
    "qis": "quantum",
    "crispr": "gene editing",
    "mrna": "rna",
    "ptsd": "post-traumatic",
    "tbi": "traumatic brain injury",
    "sud": "substance use disorder",
    "oud": "opioid use disorder",
    "als": "amyotrophic lateral sclerosis",
    "adhd": "attention deficit",
    "ckd": "kidney",
    "copd": "pulmonary",
    "ree": RARE_EARTH_CONCEPT,
    "rees": RARE_EARTH_CONCEPT,
    "lanthanide": RARE_EARTH_CONCEPT,
    "lanthanides": RARE_EARTH_CONCEPT,
    "extraction": "separation recovery processing purification",
    "pfas": PFAS_CONCEPT,
    "pfoa": PFAS_CONCEPT,
    "pfos": PFAS_CONCEPT,
    "pfhx": PFAS_CONCEPT,
    "pfna": PFAS_CONCEPT,
    "pfbs": PFAS_CONCEPT,
    "pfba": PFAS_CONCEPT,
    "pfhxa": PFAS_CONCEPT,
    "pfpea": PFAS_CONCEPT,
    "pfhpa": PFAS_CONCEPT,
    "pfda": PFAS_CONCEPT,
    "pfuna": PFAS_CONCEPT,
    "pfdoa": PFAS_CONCEPT,
    "pfca": PFAS_CONCEPT,
    "pfsa": PFAS_CONCEPT,
    "fosa": PFAS_CONCEPT,
    "hfpo-da": PFAS_CONCEPT,
    "afff": PFAS_CONCEPT,
    "perfluoroalkyl": PFAS_CONCEPT,
    "polyfluoroalkyl": PFAS_CONCEPT,
    "perfluorinat": PFAS_CONCEPT,
    "polyfluorinat": PFAS_CONCEPT,
    "perfluorooctanoic": PFAS_CONCEPT,
    "perfluorooctane": PFAS_CONCEPT,
    "fluorochemical": PFAS_CONCEPT,
    "fluorosurfactant": PFAS_CONCEPT,
    "forever": PFAS_CONCEPT,
}

ALWAYS_EXPAND_ALIASES = {
    term
    for term, expansion in QUERY_ALIASES.items()
    if expansion in {PFAS_CONCEPT, RARE_EARTH_CONCEPT}
    or term == "extraction"
}
PFAS_DESCRIPTOR_TERMS = {
    "acid", "chemical", "compound", "substance", "sulfonate",
}

QUERY_VARIANTS: dict[str, tuple[str, ...]] = {
    "analyse": ("analysi",),
    "analysi": ("analyse",),
    "bacterium": ("bacteria",),
    "bacteria": ("bacterium",),
    "child": ("children",),
    "children": ("child",),
    "criterion": ("criteria",),
    "criteria": ("criterion",),
    "datum": ("data",),
    "fungus": ("fungi",),
    "fungi": ("fungus",),
    "index": ("indicy", "indice"),
    "indicy": ("index",),
    "indice": ("index",),
    "man": ("men",),
    "men": ("man",),
    "matrix": ("matrice",),
    "matrice": ("matrix",),
    "medium": ("media",),
    "mouse": ("mice",),
    "mice": ("mouse",),
    "phenomenon": ("phenomena",),
    "phenomena": ("phenomenon",),
    "woman": ("women",),
    "women": ("woman",),
}


def query_variants(term: str) -> tuple[str, ...]:
    return (term, *QUERY_VARIANTS.get(term, ()))


def _concept_group(
    source: str,
    concept: str,
    direct_terms: set[str],
    *,
    literal_terms: tuple[str, ...],
    minimum_evidence: int = 1,
    evidence_alternatives: tuple[tuple[str, ...], ...] = (),
    evidence_phrases: tuple[str, ...] = (),
    evidence_windows: tuple[dict, ...] = (),
    evidence_mode: str = "all",
    required_unless_topic: str = "",
    required_always: bool = False,
) -> dict:
    weighted: dict[str, float] = {}
    literals = set(literal_terms)
    for term in tokenize(concept):
        weighted[term] = 1.0 if term in literals or term in direct_terms else 0.86
    if source and " " not in source:
        weighted.setdefault(source, 1.0)
    return {
        "source": source,
        "terms": list(weighted.items()),
        "minimum_evidence": minimum_evidence,
        "evidence_alternatives": evidence_alternatives,
        "evidence_phrases": evidence_phrases,
        "evidence_windows": evidence_windows,
        "evidence_mode": evidence_mode,
        "required_unless_topic": required_unless_topic,
        "required_always": required_always,
    }


def _has_ionic_liquid_context(value: str, terms: set[str]) -> bool:
    if re.search(r"ionic[\s-]+liquids?", value, re.I):
        return True
    if {"rare", "earth"} <= terms:
        return True
    return bool(terms & {
        "ree", "lanthanide", "scandium", "yttrium", "extraction",
        "separation", "recovery", "solvent", "leaching", "hydrometallurgy",
    })


def expand_query_groups(
    value: str,
    postings: dict[str, list] | None = None,
) -> list[dict]:
    """Group every alias/irregular expansion under its original query term."""
    groups: list[dict] = []
    direct_terms = list(dict.fromkeys(tokenize(value)))
    direct_term_set = set(direct_terms)
    has_pfas_alias = any(
        QUERY_ALIASES.get(term) == PFAS_CONCEPT for term in direct_terms
    )
    rare_earth_phrase = bool(re.search(
        r"\brare[\s-]+earth(?:[\s-]+elements?)?\b", value, re.I
    ))
    ionic_liquid_phrase = bool(re.search(r"\bionic[\s-]+liquids?\b", value, re.I))
    broad_call_phrase = bool(re.search(
        r"\bbroad[\s-]+agency[\s-]+announcements?\b|\bBAAs?\b", value, re.I
    ))
    basic_energy_sciences = bool(re.search(
        r"\bbasic[\s-]+energy[\s-]+sciences?\b|\bBES\b", value, re.I
    ))
    il_abbreviation = bool(re.search(r"\bILs?\b", value, re.I)) and (
        _has_ionic_liquid_context(value, direct_term_set)
    )
    emitted: set[str] = set()
    for term in direct_terms:
        if has_pfas_alias and term in PFAS_DESCRIPTOR_TERMS:
            continue
        if term in {"catalyst", "catalysi", "catalytic"}:
            if "catalysis" in emitted:
                continue
            emitted.add("catalysis")
            groups.append(_concept_group(
                term,
                CATALYSIS_CONCEPT,
                direct_term_set,
                literal_terms=(term,),
                minimum_evidence=1,
                evidence_alternatives=CATALYSIS_EVIDENCE,
                evidence_windows=CATALYST_CONTEXT_WINDOWS,
                evidence_mode="any",
            ))
            continue
        if term == "ai":
            if "artificial-intelligence" in emitted:
                continue
            emitted.add("artificial-intelligence")
            groups.append(_concept_group(
                term,
                AI_CONCEPT,
                direct_term_set,
                literal_terms=("ai",),
                minimum_evidence=1,
                evidence_alternatives=AI_EVIDENCE,
            ))
            continue
        if (
            (basic_energy_sciences and term in {"basic", "energy", "science"})
            or (basic_energy_sciences and term == "bes")
        ):
            if "basic-energy-sciences" in emitted:
                continue
            emitted.add("basic-energy-sciences")
            groups.append(_concept_group(
                "bes" if term == "bes" else "basic energy sciences",
                BASIC_ENERGY_SCIENCES_CONCEPT,
                direct_term_set,
                literal_terms=("bes",) if term == "bes" else ("basic", "energy", "science"),
                minimum_evidence=1,
                evidence_alternatives=BASIC_ENERGY_SCIENCES_EVIDENCE,
                evidence_phrases=("basic energy science", "bes"),
                required_always=True,
            ))
            continue
        if (
            (broad_call_phrase and term in {"broad", "agency", "announcement"})
            or (broad_call_phrase and term == "baa")
        ):
            if "broad-call" in emitted:
                continue
            emitted.add("broad-call")
            groups.append(_concept_group(
                "baa" if term == "baa" else "broad agency announcement",
                BROAD_CALL_CONCEPT,
                direct_term_set,
                literal_terms=("baa",) if term == "baa" else ("broad", "agency", "announcement"),
                minimum_evidence=1,
                evidence_alternatives=BROAD_CALL_EVIDENCE,
                required_always=True,
            ))
            continue
        if (
            (rare_earth_phrase and term in {"rare", "earth", "element"})
            or term in {"ree", "lanthanide"}
        ):
            if "rare-earth" in emitted:
                continue
            emitted.add("rare-earth")
            groups.append(_concept_group(
                "rare earth" if rare_earth_phrase else term,
                RARE_EARTH_CONCEPT,
                direct_term_set,
                literal_terms=("rare", "earth", "element") if rare_earth_phrase else (term,),
                evidence_alternatives=RARE_EARTH_EVIDENCE,
                required_unless_topic="Separations and membranes",
            ))
            continue
        if ionic_liquid_phrase and term in {"ionic", "liquid"}:
            if "ionic-liquid" in emitted:
                continue
            emitted.add("ionic-liquid")
            groups.append(_concept_group(
                "ionic liquid",
                IONIC_LIQUID_CONCEPT,
                direct_term_set,
                literal_terms=("ionic", "liquid"),
                minimum_evidence=2,
                evidence_alternatives=IONIC_LIQUID_EVIDENCE,
                required_always=True,
            ))
            continue
        if il_abbreviation and term in {"il", "ils"}:
            if "ionic-liquid" in emitted:
                continue
            emitted.add("ionic-liquid")
            groups.append(_concept_group(
                term,
                IONIC_LIQUID_CONCEPT,
                direct_term_set,
                literal_terms=(term,),
                minimum_evidence=2,
                evidence_alternatives=IONIC_LIQUID_EVIDENCE,
                required_always=True,
            ))
            continue
        weighted_terms: dict[str, float] = {term: 1.0}
        for variant in query_variants(term)[1:]:
            weighted_terms.setdefault(variant, 0.94)
        if not (postings and term in postings and term not in ALWAYS_EXPAND_ALIASES):
            expansion = QUERY_ALIASES.get(term)
            if expansion:
                for expanded in tokenize(expansion):
                    if expanded != term and expanded in direct_term_set:
                        continue
                    weighted_terms.setdefault(expanded, 0.86)
        groups.append({
            "source": term,
            "terms": list(weighted_terms.items()),
            "minimum_evidence": 0,
            "evidence_alternatives": (),
            "required_unless_topic": "",
            "required_always": False,
        })
    return groups


def expand_query_terms(
    value: str,
    postings: dict[str, list] | None = None,
) -> list[tuple[str, float]]:
    """Return de-duplicated direct and lightly downweighted alias terms."""
    weighted_terms: dict[str, float] = {}
    for group in expand_query_groups(value, postings):
        for term, weight in group["terms"]:
            weighted_terms[term] = max(weight, weighted_terms.get(term, 0.0))
    return list(weighted_terms.items())
