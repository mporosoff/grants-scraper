"""Conservative query expansion shared by server-side catalog search tools.

The browser equivalent lives in ``assets/search-query.js``. Keep the alias
keys and phrases synchronized; tests exercise the important contract on both
sides. Aliases are query-only so a catalog refresh is not required when the
glossary improves.
"""

from __future__ import annotations

from .build_catalog import tokenize


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
}


def expand_query_terms(
    value: str,
    postings: dict[str, list] | None = None,
) -> list[tuple[str, float]]:
    """Return de-duplicated direct and lightly downweighted alias terms."""
    direct_terms = list(dict.fromkeys(tokenize(value)))
    weighted_terms = {term: 1.0 for term in direct_terms}
    for term in direct_terms:
        if postings and term in postings:
            continue
        expansion = QUERY_ALIASES.get(term)
        if not expansion:
            continue
        for expanded in tokenize(expansion):
            weighted_terms.setdefault(expanded, 0.86)
    return list(weighted_terms.items())
