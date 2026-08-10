"""Conservative query expansion shared by server-side catalog search tools.

The browser equivalent lives in ``assets/search-query.js``. Keep the alias
keys and phrases synchronized; tests exercise the important contract on both
sides. Aliases are query-only so a catalog refresh is not required when the
glossary improves.
"""

from __future__ import annotations

from .build_catalog import tokenize


PFAS_CONCEPT = (
    "persistent contaminant contamination pollution remediation groundwater "
    "drinking wastewater water treatment purification"
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
    term for term, expansion in QUERY_ALIASES.items() if expansion == PFAS_CONCEPT
}


def expand_query_terms(
    value: str,
    postings: dict[str, list] | None = None,
) -> list[tuple[str, float]]:
    """Return de-duplicated direct and lightly downweighted alias terms."""
    direct_terms = list(dict.fromkeys(tokenize(value)))
    weighted_terms = {term: 1.0 for term in direct_terms}
    for term in direct_terms:
        if postings and term in postings and term not in ALWAYS_EXPAND_ALIASES:
            continue
        expansion = QUERY_ALIASES.get(term)
        if not expansion:
            continue
        for expanded in tokenize(expansion):
            weighted_terms.setdefault(expanded, 0.86)
    return list(weighted_terms.items())
