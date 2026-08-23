"""Conservative query expansion shared by server-side catalog search tools.

The browser equivalent lives in ``assets/search-query.js``. Keep the alias
keys and phrases synchronized; tests exercise the important contract on both
sides. Aliases are query-only so a catalog refresh is not required when the
glossary improves.
"""

from __future__ import annotations

import re

from .build_catalog import tokenize


QUERY_API_CONTRACT_VERSION = 3
PFAS_CONCEPT = (
    "persistent contaminant contamination pollution remediation groundwater "
    "drinking wastewater water treatment purification"
)
RARE_EARTH_CONCEPT = (
    "ree rare earth element lanthanide scandium yttrium cerium dysprosium erbium "
    "europium gadolinium holmium lanthanum lutetium neodymium praseodymium "
    "promethium samarium terbium thulium ytterbium"
)
RARE_EARTH_QUERY_MEMBERS = {
    "ree", "rees", "lanthanide", "scandium", "yttrium", "cerium", "dysprosium",
    "erbium", "europium", "gadolinium", "holmium", "lanthanum", "lutetium",
    "neodymium", "praseodymium", "promethium", "samarium", "terbium", "thulium",
    "ytterbium",
}
RARE_EARTH_EVIDENCE = (
    ("ree",),
    ("rare", "earth"),
    ("lanthanide",),
    ("scandium",),
    ("yttrium",),
    *((term,) for term in (
        "cerium", "dysprosium", "erbium", "europium", "gadolinium", "holmium",
        "lanthanum", "lutetium", "neodymium", "praseodymium", "promethium",
        "samarium", "terbium", "thulium", "ytterbium",
    )),
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
SEPARATION_METHOD_CONCEPT = (
    "separation separate extraction extract processing recovery recover purification "
    "solvent hydrometallurgy leaching ion exchange membrane refining"
)
SEPARATION_QUERY_TERMS = {
    "separation", "extraction", "processing", "recovery", "purification",
    "hydrometallurgy", "leach", "refin", "recycl",
}
MATERNAL_HEALTH_CONCEPT = "maternal maternity obstetric mortality morbidity pregnancy childbirth"
RURAL_CARE_CONCEPT = "rural community communities area network access delivery care"
DROUGHT_RESILIENCE_CONCEPT = "drought tolerant tolerance resilience resilient abiotic stress trait"
CROP_GENETICS_CONCEPT = "crop plant genetics genetic genomics genomic breeding cultivar germplasm trait"
ENERGY_STORAGE_CONCEPT = "energy storage battery grid-scale grid technology technologies"
LONG_DURATION_CONCEPT = "long duration long-duration seasonal extended storage"
FOUNDATION_MODEL_CONCEPT = "foundation model models composable modular generative ai"
SECURITY_RESILIENCE_CONCEPT = "secure security cybersecurity adversarial robustness robust resilience resilient attack mitigation trustworthy"
EARTH_SYSTEM_CONCEPT = "earth system sun-earth geospace coupled"
CHEMICAL_PROCESS_CONCEPT = "chemical element elements process processes chemistry cycling"
MEMBRANE_TREATMENT_CONCEPT = "membrane treatment purification separation filtration water"
RARE_DISEASE_CONCEPT = "rare disease disorder orphan genetic molecular genomic genomics sequencing"
RARE_DISEASE_MOLECULAR_CONCEPT = "rare disease disorder orphan genetic molecular genomic genomics sequencing element"
MOLECULAR_GENOMICS_CONCEPT = "molecular genetics genomic genomics sequencing variant gene"
EDUCATION_INNOVATION_CONCEPT = "education educational learning teaching pedagogy innovation"
STUDENT_SUCCESS_CONCEPT = "student success persistence retention graduation attainment"
SINGLE_CELL_CONCEPT = "single cell single-cell cellular transcriptomics sequencing"
CANCER_IMMUNOLOGY_CONCEPT = "cancer tumor oncology immune immunology immunotherapy"
ELECTROCATALYSIS_CONCEPT = "electrocatalysis electrocatalytic electrochemical catalyst catalysis redox"
AMMONIA_SYNTHESIS_CONCEPT = "ammonia synthesis synthesize nitrogen fixation production"
HIGH_TEMPERATURE_MATERIALS_CONCEPT = "high temperature composite composites thermal structural material materials"
HYPERSONIC_ENVIRONMENT_CONCEPT = "hypersonic hypersonics extreme dynamic thermal environment"
MARITIME_CONCEPT = "maritime marine naval navy ocean sea"
NAVIGATION_CONCEPT = "navigation pnt"
QUANTUM_SENSING_CONCEPT = "quantum sensing"
AGENCY_QUALIFIER_TERMS = {"doe", "nsf", "nasa", "nih"}
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
CATALYST_DESIGN_CONCEPT = "catalyst catalysis catalytic design discovery optimization screening engineering"
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
HIGH_PERFORMANCE_COMPUTING_CONCEPT = "high performance computing hpc supercomputing compute computational"
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
    concept_id: str = "",
    role: str = "",
    required: bool = False,
    evidence_policy: str = "",
    strict_evidence: bool = True,
    saturate_concept: bool = False,
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
        "concept_id": concept_id,
        "role": role,
        "required": required,
        "evidence_policy": evidence_policy,
        "strict_evidence": strict_evidence,
        "saturate_concept": saturate_concept,
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
    *,
    search_v2: bool = False,
) -> list[dict]:
    """Group every alias/irregular expansion under its original query term."""
    groups: list[dict] = []
    dotted_ree = bool(re.search(
        r"\bR\s*\.\s*E\s*\.\s*E(?:\s*\.)?s?(?![A-Za-z0-9])",
        value,
        re.I,
    ))
    direct_terms = list(dict.fromkeys(tokenize(value)))
    if search_v2 and dotted_ree:
        direct_terms = [
            "ree" if re.fullmatch(r"r\.e\.e(?:s)?", term, re.I) else term
            for term in direct_terms
        ]
        if "ree" not in direct_terms:
            direct_terms.insert(0, "ree")
        direct_terms = list(dict.fromkeys(direct_terms))
    direct_term_set = set(direct_terms)
    has_pfas_alias = any(
        QUERY_ALIASES.get(term) == PFAS_CONCEPT for term in direct_terms
    )
    critical_mineral_phrase = search_v2 and bool(re.search(
        r"\bcritical[\s-]+minerals?\b", value, re.I
    ))
    quantum_sensing_phrase = search_v2 and bool(re.search(
        r"\bquantum[\s-]+sens(?:e|ing|ors?)\b", value, re.I
    ))
    rare_earth_phrase = bool(re.search(
        r"\brare[\s-]+earth(?:[\s-]+elements?)?\b", value, re.I
    ))
    rare_earth_acronym = search_v2 and bool(
        dotted_ree or re.search(r"\bREEs?\b", value, re.I)
    )
    rare_earth_query = bool(
        rare_earth_phrase
        or rare_earth_acronym
        or set(direct_terms) & RARE_EARTH_QUERY_MEMBERS
    )
    ionic_liquid_phrase = bool(re.search(r"\bionic[\s-]+liquids?\b", value, re.I))
    solvent_extraction_phrase = search_v2 and bool(re.search(
        r"\bsolvent[\s-]+extractions?\b", value, re.I
    ))
    ion_exchange_phrase = search_v2 and bool(re.search(
        r"\bion[\s-]+exchange\b", value, re.I
    ))
    resource_recovery_phrase = search_v2 and bool(re.search(
        r"\bresource[\s-]+recovery\b", value, re.I
    ))
    maternal_health_phrase = search_v2 and bool(re.search(
        r"\bmaternal[\s-]+(?:mortality|morbidity|health)\b", value, re.I
    ))
    rural_context_phrase = search_v2 and bool(
        re.search(r"\brural\b", value, re.I)
        and re.search(
            r"\b(?:communities?|areas?|care|maternity|obstetrics?|networks?|access)\b",
            value,
            re.I,
        )
    )
    drought_resilience_phrase = search_v2 and bool(
        re.search(r"\bdrought\b", value, re.I)
        and re.search(r"\b(?:toleran(?:t|ce)|resilien(?:t|ce)|stress|trait)\b", value, re.I)
    )
    crop_genetics_phrase = search_v2 and bool(
        re.search(r"\b(?:crops?|plants?)\b", value, re.I)
        and re.search(r"\b(?:genetics?|genomics?|breeding|traits?)\b", value, re.I)
    )
    long_duration_phrase = search_v2 and bool(re.search(
        r"\blong[\s-]+duration\b", value, re.I
    ))
    energy_storage_phrase = search_v2 and bool(re.search(
        r"\benergy[\s-]+storage\b", value, re.I
    ))
    foundation_model_phrase = search_v2 and bool(re.search(
        r"\bfoundation[\s-]+models?\b", value, re.I
    ))
    model_security_context = search_v2 and foundation_model_phrase and bool(re.search(
        r"\b(?:secure|security|cybersecurity|adversarial|robust(?:ness)?|resilien(?:t|ce)|trustworthy)\b",
        value,
        re.I,
    ))
    artificial_intelligence_phrase = search_v2 and bool(re.search(
        r"\bartificial[\s-]+intelligence\b", value, re.I
    ))
    high_performance_computing_phrase = search_v2 and bool(re.search(
        r"\bhigh[\s-]+performance[\s-]+comput(?:e|ing)\b", value, re.I
    ))
    earth_system_phrase = search_v2 and bool(re.search(
        r"\b(?:sun[\s-]+earth|earth[\s-]+system)\b", value, re.I
    ))
    chemical_elements_phrase = search_v2 and bool(re.search(
        r"\bchemical[\s-]+elements?\b", value, re.I
    ))
    membrane_treatment_phrase = search_v2 and bool(
        re.search(r"\bmembranes?\b", value, re.I)
        and re.search(r"\b(?:treatment|purification|separation|filtration)\b", value, re.I)
    )
    catalyst_design_phrase = search_v2 and bool(
        re.search(r"\b(?:catalyst|catalysis|catalytic)\b", value, re.I)
        and re.search(r"\b(?:design|discovery|optimization|screening)\b", value, re.I)
    )
    rare_disease_phrase = search_v2 and bool(re.search(
        r"\brare[\s-]+(?:diseases?|disorders?)\b", value, re.I
    ))
    rare_disease_molecular_phrase = search_v2 and bool(
        re.search(r"\brare[\s-]+diseases?\b", value, re.I)
        and re.search(r"\b(?:molecular|genetics?|genomics?|elements?)\b", value, re.I)
    )
    molecular_genomics_phrase = search_v2 and bool(re.search(
        r"\b(?:molecular[\s-]+(?:genetics?|genomics?)|genomic[\s-]+sequencing)\b",
        value,
        re.I,
    ))
    education_innovation_phrase = search_v2 and bool(
        re.search(r"\b(?:education|educational)\b", value, re.I)
        and re.search(r"\binnov(?:ation|ative)\b", value, re.I)
    )
    innovation_catalyst_phrase = search_v2 and bool(re.search(
        r"\binnovation[\s-]+catalyst\b", value, re.I
    ))
    student_success_phrase = search_v2 and bool(re.search(
        r"\bstudent[\s-]+(?:success|persistence|retention|attainment)\b", value, re.I
    ))
    single_cell_phrase = search_v2 and bool(re.search(
        r"\bsingle[\s-]+cell\b", value, re.I
    ))
    cancer_immunology_phrase = search_v2 and bool(
        re.search(r"\b(?:cancer|tumou?r|oncolog)\w*\b", value, re.I)
        and re.search(r"\b(?:immune|immunolog|immunotherap)\w*\b", value, re.I)
    )
    electrocatalysis_phrase = search_v2 and bool(
        re.search(r"\belectrocatal\w*\b", value, re.I)
        and re.search(r"\bammonia\b", value, re.I)
    )
    ammonia_synthesis_phrase = search_v2 and bool(re.search(
        r"\bammonia[\s-]+(?:synthesis|production)\b", value, re.I
    ))
    high_temperature_composites_phrase = search_v2 and bool(re.search(
        r"\bhigh[\s-]+temperature\b.*\bcomposites?\b|\bcomposites?\b.*\bhigh[\s-]+temperature\b",
        value,
        re.I,
    ))
    hypersonic_environment_phrase = search_v2 and bool(re.search(
        r"\bhypersonics?\b", value, re.I
    ))
    broad_call_phrase = bool(re.search(
        r"\bbroad[\s-]+agency[\s-]+announcements?\b|\bBAAs?\b", value, re.I
    ))
    basic_energy_sciences = bool(re.search(
        r"\bbasic[\s-]+energy[\s-]+sciences?\b|\bBES\b", value, re.I
    ))
    il_abbreviation = bool(re.search(r"\bILs?\b", value, re.I)) and (
        _has_ionic_liquid_context(value, direct_term_set)
    )
    uppercase_terms = {
        token
        for raw in re.findall(r"\b[A-Z][A-Z0-9]{2,8}s?\b", value)
        for token in tokenize(raw)
    }
    emitted: set[str] = set()
    for term in direct_terms:
        if artificial_intelligence_phrase and term in {"artificial", "intelligence"}:
            if "artificial-intelligence" in emitted:
                continue
            emitted.add("artificial-intelligence")
            groups.append(_concept_group(
                "artificial intelligence", AI_CONCEPT, direct_term_set,
                literal_terms=("artificial", "intelligence"), minimum_evidence=2,
                evidence_phrases=("artificial intelligence", "machine learning"),
                concept_id="artificial-intelligence", role="method", required=True,
                evidence_policy="protected_ai", saturate_concept=True,
            ))
            continue
        if high_performance_computing_phrase and term in {"high", "performance", "comput"}:
            if "high-performance-computing" in emitted:
                continue
            emitted.add("high-performance-computing")
            groups.append(_concept_group(
                "high performance computing", HIGH_PERFORMANCE_COMPUTING_CONCEPT,
                direct_term_set,
                literal_terms=("high", "performance", "comput"), minimum_evidence=2,
                evidence_phrases=("high performance computing", "high-performance computing", "supercomputing"),
                concept_id="high-performance-computing", role="target", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
            continue
        if rare_disease_molecular_phrase and term in {
            "rare", "disease", "molecular", "genetic", "genomic", "element",
        }:
            if "rare-disease-molecular-genomics" in emitted:
                continue
            emitted.add("rare-disease-molecular-genomics")
            groups.append(_concept_group(
                "rare disease molecular genomics", RARE_DISEASE_MOLECULAR_CONCEPT,
                direct_term_set,
                literal_terms=("rare", "disease", "molecular", "genetic", "genomic", "element"),
                minimum_evidence=2,
                evidence_phrases=("rare disease", "rare genetic disorder"),
                evidence_windows=(
                    {"terms": ("rare", "disease", "molecular"), "maximum_span": 30},
                    {"terms": ("rare", "disease", "genetic"), "maximum_span": 30},
                    {"terms": ("rare", "disease", "genomic"), "maximum_span": 30},
                ),
                concept_id="rare-disease-molecular-genomics", role="target",
                required=True, evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if innovation_catalyst_phrase and term in {"innovation", "catalyst"}:
            if "education-innovation" in emitted:
                continue
            emitted.add("education-innovation")
            groups.append(_concept_group(
                "education innovation", EDUCATION_INNOVATION_CONCEPT, direct_term_set,
                literal_terms=("innovation", "catalyst"), concept_id="education-innovation",
                role="application_or_context", required=True, saturate_concept=True,
            ))
            continue
        if rare_disease_phrase and term in {"rare", "disease", "disorder"}:
            if "rare-disease" in emitted:
                continue
            emitted.add("rare-disease")
            groups.append(_concept_group(
                "rare disease", RARE_DISEASE_CONCEPT, direct_term_set,
                literal_terms=("rare", "disease", "disorder"), minimum_evidence=2,
                evidence_phrases=("rare disease", "rare disorder", "orphan disease"),
                concept_id="rare-disease", role="target", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
            continue
        if molecular_genomics_phrase and term in {"molecular", "genetic", "genomic", "sequencing"}:
            if "molecular-genomics" in emitted:
                continue
            emitted.add("molecular-genomics")
            groups.append(_concept_group(
                "molecular genomics", MOLECULAR_GENOMICS_CONCEPT, direct_term_set,
                literal_terms=("molecular", "genetic", "genomic", "sequencing"),
                evidence_phrases=("molecular genetics", "molecular genomics", "genomic sequencing"),
                concept_id="molecular-genomics", role="method", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
            continue
        if education_innovation_phrase and term in {"education", "educational", "innovation", "innovative"}:
            if "education-innovation" in emitted:
                continue
            emitted.add("education-innovation")
            groups.append(_concept_group(
                "education innovation", EDUCATION_INNOVATION_CONCEPT, direct_term_set,
                literal_terms=("education", "educational", "innovation", "innovative"),
                evidence_phrases=("education innovation", "educational innovation", "innovative education"),
                concept_id="education-innovation", role="method", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
            continue
        if student_success_phrase and term in {"student", "success", "persistence", "retention", "attainment"}:
            if "student-success" in emitted:
                continue
            emitted.add("student-success")
            groups.append(_concept_group(
                "student success", STUDENT_SUCCESS_CONCEPT, direct_term_set,
                literal_terms=("student", "success", "persistence", "retention", "attainment"),
                evidence_phrases=("student success", "student persistence", "student retention", "student attainment"),
                concept_id="student-success", role="target", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
            continue
        if single_cell_phrase and term in {"single", "cell"}:
            if "single-cell-biology" in emitted:
                continue
            emitted.add("single-cell-biology")
            groups.append(_concept_group(
                "single cell", SINGLE_CELL_CONCEPT, direct_term_set,
                literal_terms=("single", "cell"), minimum_evidence=2,
                evidence_phrases=("single cell",), concept_id="single-cell-biology",
                role="method", required=True, evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if cancer_immunology_phrase and term in {"cancer", "tumor", "oncology", "immune", "immunology", "immunotherapy"}:
            if "cancer-immunology" in emitted:
                continue
            emitted.add("cancer-immunology")
            groups.append(_concept_group(
                "cancer immunology", CANCER_IMMUNOLOGY_CONCEPT, direct_term_set,
                literal_terms=("cancer", "tumor", "oncology", "immune", "immunology", "immunotherapy"),
                evidence_phrases=("cancer immunology", "cancer immunotherapy", "tumor immunology"),
                concept_id="cancer-immunology", role="target", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
            continue
        if electrocatalysis_phrase and term.startswith("electrocatal"):
            if "electrocatalysis" in emitted:
                continue
            emitted.add("electrocatalysis")
            groups.append(_concept_group(
                term, ELECTROCATALYSIS_CONCEPT, direct_term_set,
                literal_terms=(term,), concept_id="electrocatalysis", role="method",
                required=True, saturate_concept=True,
            ))
            continue
        if ammonia_synthesis_phrase and term in {"ammonia", "synthesi", "synthesize", "synthetic", "production"}:
            if "ammonia-synthesis" in emitted:
                continue
            emitted.add("ammonia-synthesis")
            groups.append(_concept_group(
                "ammonia synthesis", AMMONIA_SYNTHESIS_CONCEPT, direct_term_set,
                literal_terms=("ammonia", "synthesi", "synthesize", "synthetic", "production"),
                minimum_evidence=2, evidence_phrases=("ammonia synthesis", "ammonia production"),
                concept_id="ammonia-synthesis", role="target", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
            continue
        if high_temperature_composites_phrase and term in {"high", "temperature", "composite"}:
            if "high-temperature-materials" in emitted:
                continue
            emitted.add("high-temperature-materials")
            groups.append(_concept_group(
                "high temperature composites", HIGH_TEMPERATURE_MATERIALS_CONCEPT, direct_term_set,
                literal_terms=("high", "temperature", "composite"), minimum_evidence=2,
                concept_id="high-temperature-materials", role="target", required=True,
                evidence_policy="protected_high_temperature_composites", saturate_concept=True,
            ))
            continue
        if hypersonic_environment_phrase and term == "hypersonic":
            if "hypersonic-environment" in emitted:
                continue
            emitted.add("hypersonic-environment")
            groups.append(_concept_group(
                "hypersonic environment", HYPERSONIC_ENVIRONMENT_CONCEPT, direct_term_set,
                literal_terms=("hypersonic",), concept_id="hypersonic-environment",
                role="application_or_context", required=True,
                evidence_policy="protected_hypersonic", saturate_concept=True,
            ))
            continue
        if quantum_sensing_phrase and term in {"quantum", "sens"}:
            if "quantum-sensing" in emitted:
                continue
            emitted.add("quantum-sensing")
            groups.append(_concept_group(
                "quantum sensing",
                QUANTUM_SENSING_CONCEPT,
                direct_term_set,
                literal_terms=("quantum", "sens"),
                minimum_evidence=2,
                concept_id="quantum-sensing",
                role="method",
                required=True,
            ))
            continue
        if critical_mineral_phrase and term in {"critical", "mineral"}:
            if "critical-minerals" in emitted:
                continue
            emitted.add("critical-minerals")
            groups.append(_concept_group(
                "critical mineral",
                "critical mineral",
                direct_term_set,
                literal_terms=("critical", "mineral"),
                minimum_evidence=2,
                evidence_phrases=("critical mineral",),
                concept_id="critical-minerals",
                role="target",
                required=True,
                evidence_policy="controlled_compound",
            ))
            continue
        if critical_mineral_phrase and term == "workforce":
            groups.append(_concept_group(
                term,
                "workforce worker",
                direct_term_set,
                literal_terms=(term,),
                concept_id="literal:workforce",
                role="application_or_context",
                required=True,
            ))
            continue
        if maternal_health_phrase and term in {
            "maternal", "mortality", "morbidity", "health",
        }:
            if "maternal-health" in emitted:
                continue
            emitted.add("maternal-health")
            groups.append(_concept_group(
                "maternal health",
                MATERNAL_HEALTH_CONCEPT,
                direct_term_set,
                literal_terms=("maternal", "mortality", "morbidity", "health"),
                evidence_phrases=("maternal mortality", "maternal morbidity", "maternal health", "maternity"),
                concept_id="maternal-health",
                role="target",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if rural_context_phrase and term in {
            "rural", "community", "area", "care", "network", "access",
        }:
            if "rural-care-context" in emitted:
                continue
            emitted.add("rural-care-context")
            groups.append(_concept_group(
                "rural care",
                RURAL_CARE_CONCEPT,
                direct_term_set,
                literal_terms=("rural", "community", "area", "care", "network", "access"),
                evidence_phrases=("rural care", "rural area", "rural community", "rural maternity", "rural obstetric", "rural network"),
                concept_id="rural-care-context",
                role="application_or_context",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if drought_resilience_phrase and term in {
            "drought", "tolerant", "tolerance", "resilient", "resilience", "stress", "trait",
        }:
            if "drought-resilience" in emitted:
                continue
            emitted.add("drought-resilience")
            groups.append(_concept_group(
                "drought resilience",
                DROUGHT_RESILIENCE_CONCEPT,
                direct_term_set,
                literal_terms=("drought", "tolerant", "tolerance", "resilient", "resilience", "stress", "trait"),
                evidence_phrases=("drought tolerant", "drought tolerance", "drought resilience", "abiotic stress"),
                concept_id="drought-resilience",
                role="target",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if crop_genetics_phrase and term in {
            "crop", "plant", "genetic", "genomic", "breeding", "trait",
        }:
            if "crop-genetics" in emitted:
                continue
            emitted.add("crop-genetics")
            groups.append(_concept_group(
                "crop genetics",
                CROP_GENETICS_CONCEPT,
                direct_term_set,
                literal_terms=("crop", "plant", "genetic", "genomic", "breeding", "trait"),
                evidence_phrases=("crop genetics", "crop genomics", "crop breeding", "plant genetics", "plant genomics", "plant breeding"),
                concept_id="crop-genetics",
                role="method",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if long_duration_phrase and term in {"long", "duration"}:
            if "long-duration" in emitted:
                continue
            emitted.add("long-duration")
            groups.append(_concept_group(
                "long duration",
                LONG_DURATION_CONCEPT,
                direct_term_set,
                literal_terms=("long", "duration"),
                minimum_evidence=2,
                evidence_phrases=("long duration",),
                concept_id="long-duration",
                role="application_or_context",
                required=True,
                evidence_policy="controlled_compound",
            ))
            continue
        if energy_storage_phrase and term in {"energy", "storage"}:
            if "energy-storage" in emitted:
                continue
            emitted.add("energy-storage")
            groups.append(_concept_group(
                "energy storage",
                ENERGY_STORAGE_CONCEPT,
                direct_term_set,
                literal_terms=("energy", "storage"),
                minimum_evidence=2,
                evidence_phrases=("energy storage",),
                concept_id="energy-storage",
                role="target",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if model_security_context and term in {
            "secure", "security", "cybersecurity", "adversarial", "robustness",
            "robust", "resilience", "resilient", "trustworthy",
        }:
            if "security-resilience" in emitted:
                continue
            emitted.add("security-resilience")
            groups.append(_concept_group(
                "security resilience",
                SECURITY_RESILIENCE_CONCEPT,
                direct_term_set,
                literal_terms=(term,),
                concept_id="security-resilience",
                role="application_or_context",
                required=True,
                evidence_policy="protected_ai_security",
                saturate_concept=True,
            ))
            continue
        if foundation_model_phrase and term in {"foundation", "model"}:
            if "foundation-models" in emitted:
                continue
            emitted.add("foundation-models")
            groups.append(_concept_group(
                "foundation models",
                FOUNDATION_MODEL_CONCEPT,
                direct_term_set,
                literal_terms=("foundation", "model"),
                minimum_evidence=2,
                evidence_phrases=("foundation model",),
                concept_id="foundation-models",
                role="target",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if earth_system_phrase and term in {"earth", "sun-earth", "system"}:
            if "earth-system" in emitted:
                continue
            emitted.add("earth-system")
            groups.append(_concept_group(
                "earth system",
                EARTH_SYSTEM_CONCEPT,
                direct_term_set,
                literal_terms=("earth", "sun-earth", "system"),
                minimum_evidence=2,
                evidence_phrases=("earth system", "sun earth"),
                concept_id="earth-system",
                role="target",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if chemical_elements_phrase and term in {"chemical", "element"}:
            if "chemical-processes" in emitted:
                continue
            emitted.add("chemical-processes")
            groups.append(_concept_group(
                "chemical elements",
                CHEMICAL_PROCESS_CONCEPT,
                direct_term_set,
                literal_terms=("chemical", "element"),
                evidence_phrases=("chemical element", "chemical process"),
                concept_id="chemical-processes",
                role="method",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if membrane_treatment_phrase and term in {
            "membrane", "treatment", "purification", "separation", "filtration",
        }:
            if "membrane-treatment" in emitted:
                continue
            emitted.add("membrane-treatment")
            groups.append(_concept_group(
                "membrane treatment",
                MEMBRANE_TREATMENT_CONCEPT,
                direct_term_set,
                literal_terms=("membrane", "treatment", "purification", "separation", "filtration"),
                minimum_evidence=2,
                evidence_phrases=("membrane treatment", "membrane purification", "membrane separation", "membrane filtration"),
                concept_id="membrane-treatment",
                role="method",
                required=True,
                evidence_policy="controlled_compound",
                saturate_concept=True,
            ))
            continue
        if has_pfas_alias and term in PFAS_DESCRIPTOR_TERMS:
            continue
        if has_pfas_alias and QUERY_ALIASES.get(term) == PFAS_CONCEPT:
            if "pfas-contamination" in emitted:
                continue
            emitted.add("pfas-contamination")
            groups.append(_concept_group(
                term,
                PFAS_CONCEPT,
                direct_term_set,
                literal_terms=(term,),
                concept_id="pfas-contamination",
                role="target",
                required=True,
                evidence_policy="protected_pfas",
                saturate_concept=True,
            ))
            continue
        if catalyst_design_phrase and term in {
            "catalyst", "catalysi", "catalytic", "design", "discovery",
            "optimization", "screening",
        }:
            if "catalyst-design" in emitted:
                continue
            emitted.add("catalyst-design")
            groups.append(_concept_group(
                "catalyst design", CATALYST_DESIGN_CONCEPT, direct_term_set,
                literal_terms=("catalyst", "catalysi", "catalytic", "design", "discovery", "optimization", "screening"),
                minimum_evidence=2,
                evidence_phrases=("catalyst design", "catalyst discovery", "catalyst optimization", "catalyst screening", "catalytic design"),
                concept_id="catalyst-design", role="target_and_method", required=True,
                evidence_policy="controlled_compound", saturate_concept=True,
            ))
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
                concept_id="catalysis" if search_v2 else "",
                role="method" if search_v2 else "",
                required=search_v2,
                strict_evidence=False,
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
                concept_id="artificial-intelligence" if search_v2 else "",
                role="method" if search_v2 else "",
                required=search_v2,
                evidence_policy="protected_ai" if search_v2 else "",
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
                concept_id="basic-energy-sciences" if search_v2 else "",
                role="program_or_agency_qualifier" if search_v2 else "",
                required=search_v2,
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
                concept_id="broad-call" if search_v2 else "",
                role="program_or_agency_qualifier" if search_v2 else "",
                required=search_v2,
            ))
            continue
        if (
            (rare_earth_phrase and term in {
                "rare", "earth", "element", "rare-earth", "rare-earth-element",
            })
            or term in RARE_EARTH_QUERY_MEMBERS
            or (search_v2 and (term == "rees" or (rare_earth_acronym and term == "ree")))
        ):
            if "rare-earth" in emitted:
                continue
            emitted.add("rare-earth")
            groups.append(_concept_group(
                "rare earth" if rare_earth_phrase else ("ree" if search_v2 else term),
                RARE_EARTH_CONCEPT,
                direct_term_set,
                literal_terms=("rare", "earth", "element") if rare_earth_phrase else (("ree",) if search_v2 else (term,)),
                evidence_alternatives=RARE_EARTH_EVIDENCE,
                required_unless_topic="" if search_v2 else "Separations and membranes",
                required_always=search_v2,
                concept_id="rare-earth-elements" if search_v2 else "",
                role="target" if search_v2 else "",
                required=search_v2,
                evidence_policy="protected_rare_earth" if search_v2 else "",
                saturate_concept=search_v2,
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
                concept_id="ionic-liquid-extraction" if search_v2 else "",
                role="method" if search_v2 else "",
                required=search_v2,
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
                concept_id="ionic-liquid-extraction" if search_v2 else "",
                role="method" if search_v2 else "",
                required=search_v2,
            ))
            continue
        if rare_earth_query and solvent_extraction_phrase and term in {"solvent", "extraction"}:
            if "separations" in emitted:
                continue
            emitted.add("separations")
            groups.append(_concept_group(
                "solvent extraction",
                SEPARATION_METHOD_CONCEPT,
                direct_term_set,
                literal_terms=("solvent", "extraction"),
                minimum_evidence=2,
                evidence_phrases=("solvent extraction",),
                required_always=True,
                concept_id="separations",
                role="method",
                required=True,
                evidence_policy="technical_separation",
                saturate_concept=True,
            ))
            continue
        if ion_exchange_phrase and term in {"ion", "exchange"}:
            if "separations" in emitted:
                continue
            emitted.add("separations")
            groups.append(_concept_group(
                "ion exchange",
                SEPARATION_METHOD_CONCEPT,
                direct_term_set,
                literal_terms=("ion", "exchange"),
                minimum_evidence=2,
                evidence_phrases=("ion exchange",),
                required_always=rare_earth_query,
                concept_id="separations",
                role="method",
                required=True,
                evidence_policy="technical_separation",
                saturate_concept=True,
            ))
            continue
        if resource_recovery_phrase and term in {"resource", "recovery"}:
            if "separations" in emitted:
                continue
            emitted.add("separations")
            groups.append(_concept_group(
                "resource recovery",
                SEPARATION_METHOD_CONCEPT,
                direct_term_set,
                literal_terms=("resource", "recovery"),
                required_always=rare_earth_query,
                concept_id="separations",
                role="method",
                required=True,
                evidence_policy="technical_separation",
                saturate_concept=True,
            ))
            continue
        if search_v2 and term in SEPARATION_QUERY_TERMS:
            if "separations" in emitted:
                continue
            emitted.add("separations")
            groups.append(_concept_group(
                term,
                SEPARATION_METHOD_CONCEPT,
                direct_term_set,
                literal_terms=(term,),
                required_always=rare_earth_query,
                concept_id="separations",
                role="method",
                required=True,
                evidence_policy="technical_separation",
                saturate_concept=True,
            ))
            continue
        if search_v2 and term == "maritime":
            groups.append(_concept_group(
                term,
                MARITIME_CONCEPT,
                direct_term_set,
                literal_terms=(term,),
                concept_id="literal:maritime",
                role="application_or_context",
                required=True,
            ))
            continue
        if search_v2 and term == "navigation":
            groups.append(_concept_group(
                term,
                NAVIGATION_CONCEPT,
                direct_term_set,
                literal_terms=(term,),
                concept_id="literal:navigation",
                role="application_or_context",
                required=True,
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
        group = {
            "source": term,
            "terms": list(weighted_terms.items()),
            "minimum_evidence": 0,
            "evidence_alternatives": (),
            "required_unless_topic": "",
            "required_always": False,
        }
        if search_v2:
            group.update({
                "concept_id": f"literal:{term}",
                "role": (
                    "program_or_agency_qualifier"
                    if term in AGENCY_QUALIFIER_TERMS
                    else "application_or_context"
                ),
                "required": True,
                "required_always": term in AGENCY_QUALIFIER_TERMS,
                "exact_indexed_acronym": term in uppercase_terms and len(term) <= 4,
                "strict_evidence": False,
            })
        groups.append(group)
    return groups


def expand_query_terms(
    value: str,
    postings: dict[str, list] | None = None,
    *,
    search_v2: bool = False,
) -> list[tuple[str, float]]:
    """Return de-duplicated direct and lightly downweighted alias terms."""
    weighted_terms: dict[str, float] = {}
    for group in expand_query_groups(value, postings, search_v2=search_v2):
        for term, weight in group["terms"]:
            weighted_terms[term] = max(weight, weighted_terms.get(term, 0.0))
    return list(weighted_terms.items())
