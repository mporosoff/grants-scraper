"""Phase 4 engine: ChemE faculty publication profiles + solicitation matching.

Two stages:

1. ``build_profiles`` — for each Chemical & Sustainability Engineering faculty
   member, resolve their OpenAlex author record (preferring University of
   Rochester affiliation) and build a research profile from their top OpenAlex
   concepts/topics and recent publication titles. Writes ``faculty_profiles.json``.
   OpenAlex is free and needs no key; ``OPENALEX_MAILTO`` can opt into its
   polite pool without hard-coding a personal address.

2. ``match_to_catalog`` — score every opportunity in ``data/opportunities.js``
   against each faculty profile by topic/keyword overlap, and emit
   ``data/faculty_matches.js`` for the (forthcoming) internal team-match page,
   including simple multi-PI groupings for large/center solicitations.

Stage 1 is runnable now (network only). Stage 2 is wired into the catalog
pipeline and intentionally conservative: focused research concepts establish
eligibility, catalog topics only corroborate that evidence, and recency is
balanced with relevance after low-confidence matches are removed.

Usage:
    python -m scripts.faculty_match profiles --out faculty_profiles.json
    python -m scripts.faculty_match match --catalog data/opportunities.js \
        --profiles faculty_profiles.json --out data/faculty_matches.js
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
import re
import time
import urllib.parse
import urllib.request

from scripts.currentness import record_is_current

OPENALEX = "https://api.openalex.org"
OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip()
ROCHESTER_HINT = "university of rochester"        # exclude "Rochester Institute of Technology"

# Core Chemical & Sustainability Engineering faculty (Hajim, 2026).
FACULTY = [
    "Mitchell Anthamatten", "Yasemin Basdogan", "Pooja Rajendra Bhalode",
    "Siddharth Deshpande", "Gang Fan", "David G. Foster",
    "Darren Lipomi", "Allison J. Lopatkin", "Astrid M. Muller",
    "Marc D. Porosoff", "Alexander A. Shestopalov", "Wyatt E. Tenhaeff",
    "Matthew Z. Yates",
]


def _get(url: str) -> dict:
    request_url = url
    user_agent = "Funding-Finder-FacultyMatch/1.0"
    if OPENALEX_MAILTO:
        sep = "&" if "?" in url else "?"
        request_url = f"{url}{sep}mailto={urllib.parse.quote(OPENALEX_MAILTO)}"
        user_agent = f"{user_agent} ({OPENALEX_MAILTO})"
    req = urllib.request.Request(
        request_url,
        headers={"User-Agent": user_agent},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _affiliation_names(author: dict) -> str:
    names = []
    for inst in author.get("last_known_institutions") or []:
        if inst.get("display_name"):
            names.append(inst["display_name"])
    for aff in author.get("affiliations") or []:
        inst = (aff.get("institution") or {})
        if inst.get("display_name"):
            names.append(inst["display_name"])
    return " | ".join(names)


def find_author(name: str) -> dict | None:
    """Best OpenAlex author for a name that is actually affiliated with the
    University of Rochester. Returns None when no confident UR match exists, so
    we omit the person rather than attach a same-named stranger's publications
    (that kind of mis-resolution previously produced incorrect profiles)."""
    data = _get(f"{OPENALEX}/authors?search={urllib.parse.quote(name)}&per_page=15")
    results = data.get("results") or []
    rochester = [a for a in results
                 if ROCHESTER_HINT in _affiliation_names(a).lower()]
    if not rochester:
        return None
    best = max(rochester, key=lambda a: a.get("works_count") or 0)
    best["_matched_rochester"] = True
    return best


def recent_titles(author_id: str, limit: int = 12) -> list[str]:
    aid = author_id.rsplit("/", 1)[-1]
    data = _get(
        f"{OPENALEX}/works?filter=author.id:{aid}"
        f"&sort=publication_date:desc&per_page={limit}"
    )
    return [w.get("display_name") for w in (data.get("results") or [])
            if w.get("display_name")]


def build_profiles() -> list[dict]:
    profiles = []
    for name in FACULTY:
        try:
            author = find_author(name)
        except Exception as exc:  # network hiccup: record and continue
            profiles.append({"name": name, "error": str(exc)})
            continue
        if not author:
            profiles.append({"name": name,
                             "error": "no University of Rochester match in OpenAlex"})
            continue
        concepts = [c.get("display_name") for c in (author.get("x_concepts") or [])
                    if (c.get("score") or 0) >= 10][:12]
        topics = [t.get("display_name") for t in (author.get("topics") or [])][:8]
        try:
            titles = recent_titles(author.get("id", ""))
        except Exception:
            titles = []
        profiles.append({
            "name": name,
            "openalex_id": author.get("id"),
            "resolved_name": author.get("display_name"),
            "affiliation": _affiliation_names(author),
            "matched_rochester": author.get("_matched_rochester", False),
            "works_count": author.get("works_count"),
            "concepts": concepts,
            "topics": topics,
            "recent_titles": titles,
        })
        time.sleep(0.3)
    return profiles


# --------------------------------------------------------------------------- #
# Stage 2: match profiles against the opportunity catalog (v1 keyword/topic)
# --------------------------------------------------------------------------- #
_WORD_RE = re.compile(r"[a-z][a-z0-9\-]{2,}")
# Generic words are stripped so a shared key phrase must overlap on *distinctive*
# terms, not filler like "research"/"program"/"science".
_STOP = set("""the and for with from this that are was into over out per via
research program programs grant grants funding award awards project projects
support national university
universities institute department departments studies study development
applications application advancing advanced approaches approach based using their
which will been more also may can under new toward towards related general
foundation opportunity opportunities proposal proposals faculty investigator
investigators""".split())

# Focused research concepts per PI, verified against the University of Rochester
# Chemical and Sustainability Engineering faculty directory and supplemented by
# recent publications. These override OpenAlex's auto topics, which mis-resolved
# several people and attached over-broad tags. Each phrase is specific enough to
# establish fit while broad enough to catch adjacent funding language.
FACULTY_KEYTERMS: dict[str, list[str]] = {
    "Mitchell Anthamatten": [
        "macromolecular self-assembly", "associative and functional polymers",
        "nanostructured polymer materials", "polymer interfacial phenomena",
        "optoelectronic polymer materials", "vapor deposition polymerization"],
    "Yasemin Basdogan": [
        "machine learning for computational materials design",
        "molecular dynamics simulation", "quantum chemistry",
        "polymer solution modeling", "computational catalysis",
        "CO2 separation membranes"],
    "Pooja Rajendra Bhalode": [
        "process systems engineering", "multiscale molecules-to-systems modeling",
        "physics and data-driven hybrid modeling", "powder flow modeling",
        "sustainable process design", "solvent-based extraction"],
    "Siddharth Deshpande": [
        "atomic modeling of solid-liquid interfaces",
        "atomic modeling of solid-gas interfaces",
        "machine learning for catalyst discovery", "heterogeneous catalysis",
        "electrocatalysis at interfaces", "battery interface modeling"],
    "Gang Fan": [
        "bio-inspired catalysis", "polymer chemistry and plastic upcycling",
        "bioelectrochemistry", "biosensors", "synthetic biology",
        "metabolic engineering for environmental remediation"],
    "David G. Foster": [
        "transport phenomena", "computational fluid dynamics",
        "microfluidic cancer cell capture", "nanoparticle capture coatings",
        "biomedical transport modeling", "fluid mechanics education"],
    "Darren Lipomi": [
        "organic and flexible electronics", "conducting polymers",
        "stretchable semiconductors", "mechanical properties of organic electronics",
        "electrotactile haptics", "wearable bioelectronic interfaces"],
    "Allison J. Lopatkin": [
        "antibiotic resistance", "plasmid dynamics and horizontal gene transfer",
        "engineered microbial communities", "microbial systems biology",
        "metabolic engineering", "computational models of bacterial resistance"],
    "Astrid M. Muller": [
        "electrocatalytic aqueous PFAS defluorination",
        "organic electrooxidation through water activation",
        "selective carbon dioxide reduction", "electrode microenvironments",
        "pulsed-laser nanoparticle synthesis", "nanocatalyst structure-function"],
    "Marc D. Porosoff": [
        "carbon dioxide capture and conversion", "heterogeneous thermal catalysis",
        "catalyst structure-property relationships", "reactive separations",
        "C1 chemistry and light alkane upgrading",
        "catalyst representation with large language models"],
    "Alexander A. Shestopalov": [
        "surface chemistry and molecular monolayers",
        "surface patterning and contact printing", "nanostructured materials",
        "interfacial thermodynamics", "organic thin-film coatings",
        "self-assembled monolayers"],
    "Wyatt E. Tenhaeff": [
        "lithium metal batteries", "solid electrolyte interphase",
        "solid-state battery electrolytes", "battery interfacial engineering",
        "polymer thin-film electrolytes", "vacuum deposition processing"],
    "Matthew Z. Yates": [
        "functional surfaces and coatings", "sorbent polymers for chemical sensing",
        "waveguide-enhanced Raman sensing", "electrochemical sensors",
        "electrochemical surface modification", "open-source electrochemistry hardware"],
}

# Human-readable synthesis of each official profile. The matcher uses the
# focused concepts above, while these summaries preserve the broader research
# context that motivated those concepts and can be shown by the interface.
FACULTY_RESEARCH_SUMMARIES: dict[str, str] = {
    "Mitchell Anthamatten": (
        "Develops associative and functional polymers, macromolecular self-assembly, "
        "nanostructured and optoelectronic polymer materials, and vapor-deposited "
        "polymer interfaces."
    ),
    "Yasemin Basdogan": (
        "Uses quantum chemistry, molecular dynamics, and machine learning to design "
        "polymers, solutions, catalytic materials, and separation media."
    ),
    "Pooja Rajendra Bhalode": (
        "Builds multiscale, physics-informed, and data-driven process models for "
        "sustainable process systems, powder flow, and solvent-based separations."
    ),
    "Siddharth Deshpande": (
        "Models solid-liquid and solid-gas interfaces and develops data-driven methods "
        "for heterogeneous catalysis, electrocatalysis, and battery interfaces."
    ),
    "Gang Fan": (
        "Combines polymer chemistry, bio-inspired catalysis, synthetic biology, "
        "bioelectrochemistry, and metabolic engineering for plastic upcycling, sensing, "
        "and environmental remediation."
    ),
    "David G. Foster": (
        "Studies transport phenomena and computational fluid dynamics, including "
        "microfluidic and nanoparticle-coating approaches for capturing circulating cells."
    ),
    "Darren Lipomi": (
        "Develops conducting and semiconducting polymers for flexible electronics, "
        "wearable biointerfaces, medical devices, and electrotactile haptics."
    ),
    "Allison J. Lopatkin": (
        "Uses systems and synthetic biology, microbial community engineering, mathematical "
        "modeling, and machine learning to study metabolism, horizontal gene transfer, and "
        "antibiotic resistance."
    ),
    "Astrid M. Muller": (
        "Develops nanocatalysts and electrode microenvironments for aqueous PFAS "
        "defluorination, selective carbon dioxide reduction, and organic electrooxidation, "
        "including controlled pulsed-laser synthesis."
    ),
    "Marc D. Porosoff": (
        "Develops heterogeneous thermal catalysts and reactive separations for carbon "
        "dioxide capture and conversion, C1 chemistry, and light-alkane upgrading, with "
        "data and language-model representations of catalyst behavior."
    ),
    "Alexander A. Shestopalov": (
        "Studies molecularly engineered surfaces, monolayers, surface patterning, "
        "nanostructured materials, organic coatings, and interfacial thermodynamics."
    ),
    "Wyatt E. Tenhaeff": (
        "Engineers interfaces, solid electrolytes, and polymer thin films for solid-state "
        "and lithium-metal batteries using thin-film synthesis and vacuum processing."
    ),
    "Matthew Z. Yates": (
        "Develops functional surfaces and coatings, electrochemical and Raman sensors, "
        "surface-modification methods, and open-source electrochemistry hardware."
    ),
}

# Curated program-topic domains per PI, drawn from the catalog's controlled
# ``topic_areas`` vocabulary. Chosen conservatively and only where central to the
# person's work. These tags can corroborate concept-level evidence, but never
# establish a match by themselves because catalog topic tagging is intentionally
# broad and occasionally noisy.
FACULTY_DOMAINS: dict[str, list[str]] = {
    "Mitchell Anthamatten": ["Materials science", "Manufacturing"],
    "Yasemin Basdogan": [
        "Catalysis and reaction engineering", "Separations and membranes",
        "Materials science", "Carbon management",
        "Artificial intelligence and machine learning", "Energy"],
    "Pooja Rajendra Bhalode": [
        "Manufacturing", "Artificial intelligence and machine learning"],
    "Siddharth Deshpande": [
        "Catalysis and reaction engineering", "Energy", "Materials science",
        "Artificial intelligence and machine learning"],
    "Gang Fan": [
        "Biology and biotechnology", "Catalysis and reaction engineering",
        "Carbon management", "Materials science", "Environmental science"],
    "David G. Foster": ["Materials science", "Biology and biotechnology"],
    "Darren Lipomi": ["Materials science", "Manufacturing"],
    "Allison J. Lopatkin": [
        "Biology and biotechnology", "Infectious disease", "Public health",
        "Environmental science"],
    "Astrid M. Muller": [
        "Catalysis and reaction engineering", "Energy", "Carbon management",
        "Environmental science", "Materials science"],
    "Marc D. Porosoff": [
        "Catalysis and reaction engineering", "Carbon management", "Energy",
        "Materials science"],
    "Alexander A. Shestopalov": ["Materials science", "Manufacturing"],
    "Wyatt E. Tenhaeff": ["Energy", "Materials science", "Manufacturing"],
    "Matthew Z. Yates": [
        "Materials science", "Separations and membranes",
        "Catalysis and reaction engineering"],
}


def _load_catalog(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as catalog_file:
        text = catalog_file.read()
    start = text.index("{")
    obj = json.loads(text[start:].rstrip().rstrip(";"))
    return obj.get("opportunities", obj.get("records", []))


def _sig_words(phrase: str) -> list[str]:
    return [w for w in _WORD_RE.findall((phrase or "").lower()) if w not in _STOP]


def _phrase_hit(sig: list[str], opp_tokens: list[str]) -> bool:
    """A key phrase hits only when its distinctive words occur close together.

    Short phrases require every concept word. Longer phrases may omit one word,
    but the evidence must fit inside a compact token window; scattered mentions
    across a long notice are not research-fit evidence.

    Generic words remain useful inside a focused phrase (for example,
    "metabolic engineering"), but never qualify on their own because short
    phrases require complete, proximate coverage."""
    orig_len = len(sig)
    if not sig:
        return False
    if orig_len == 1:
        return sig[0] in opp_tokens
    if len(sig) < 2:
        return False
    need = len(sig) if len(sig) <= 3 else max(3, (3 * len(sig) + 3) // 4)
    window_size = len(sig) + 4
    sig_set = set(sig)
    for start in range(len(opp_tokens)):
        window = set(opp_tokens[start:start + window_size])
        if len(sig_set & window) >= need:
            return True
    return False


def _key_terms(profile: dict) -> list[str]:
    """5-8 descriptive key phrases for a PI: a hand-curated override if provided,
    otherwise the PI's top OpenAlex research topics."""
    if profile["name"] in FACULTY_KEYTERMS:
        return [t for t in FACULTY_KEYTERMS[profile["name"]] if t][:8]
    seen, terms = set(), []
    for t in (profile.get("topics") or []):
        t = re.sub(r"\s+", " ", t or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            terms.append(t)
    return terms[:8]


# --------------------------------------------------------------------------- #
# Program-topic domains. A PI's specific work is mapped onto the catalog's
# controlled ``topic_areas`` vocabulary. These domains are context and may
# corroborate focused phrase evidence; they never establish eligibility.
# Keys are catalog topic_areas; values are substrings sought in a PI profile.
# --------------------------------------------------------------------------- #
DOMAIN_LEXICON: dict[str, list[str]] = {
    "Catalysis and reaction engineering":
        ["cataly", "electrocataly", "photocataly", "reaction engineering",
         "kinetics", "water-gas shift", "hydrogenation"],
    "Energy":
        ["energy", "fuel cell", "biofuel", "fuel", "battery", "batteries",
         "electrochem", "solar", "photovolta", "combustion", "hydrogen",
         "electroly", "power grid", "renewable"],
    "Carbon management":
        ["co2", "carbon dioxide", "carbon capture", "carbon utiliz",
         "decarboniz", "sequestrat", "direct air capture", "syngas"],
    "Materials science":
        ["material", "polymer", "nanomaterial", "thin film", "crystal",
         "metal-organic framework", "mof", "composite", "coating", "graphene",
         "2d material", "semiconductor", "nanoparticle", "self-assembl"],
    "Separations and membranes":
        ["membrane", "gas separation", "adsorp", "filtration", "distillation",
         "chromatograph", "ion exchange"],
    "Manufacturing":
        ["manufactur", "additive manufactur", "3d printing", "fabrication",
         "roll-to-roll", "process intensification", "scale-up"],
    "Artificial intelligence and machine learning":
        ["machine learning", "deep learning", "neural network",
         "artificial intelligence", "data-driven"],
    "Quantum science": ["quantum"],
    "Biology and biotechnology":
        ["biolog", "biotechnolog", "microb", "protein", "synthetic biology",
         "enzyme", "antibiotic", "bioreactor", "metabolic", "fermentation"],
    "Environmental science":
        ["environ", "pollut", "emission", "sustainab", "remediation",
         "air quality"],
    "Water":
        ["desalinat", "wastewater", "water treatment", "drinking water",
         "water purification", "water resources"],
    "Public health":
        ["clinical trial", "drug delivery", "therapeutic", "pharmaceutic",
         "vaccine", "diagnostic"],
    "Climate change":
        ["climate", "greenhouse gas", "global warming"],
    "Space and aeronautics":
        ["aerospace", "spacecraft", "aeronautic", "propulsion",
         "in situ resource"],
}

# Vocabulary used by the live graded team matcher. Unlike DOMAIN_LEXICON,
# these phrases deliberately omit single umbrella words such as ``energy`` or
# ``materials``; corpus frequency further reduces the weight of common terms.
THEME_LEXICON: dict[str, list[str]] = {
    "Catalysis and reaction engineering": [
        "catalyst", "catalytic", "catalysis", "electrocataly",
        "photocataly", "reaction engineering", "reaction kinetics",
        "water-gas shift", "hydrogenation", "dehydrogenation", "reforming"],
    "Energy": [
        "energy conversion", "energy storage", "fuel cell", "biofuel",
        "battery", "electrochem", "solar fuel", "photovolta", "combustion",
        "hydrogen production", "electrolyzer", "renewable energy",
        "clean energy", "energy efficiency"],
    "Carbon management": [
        "carbon dioxide", "carbon capture", "carbon utilization", "decarboniz",
        "sequestrat", "direct air capture", "syngas", "co2 reduction",
        "co2 conversion", "negative emissions", "carbon-neutral"],
    "Materials science": [
        "advanced materials", "polymer", "nanomaterial", "thin film",
        "crystalline", "metal-organic framework", "composite", "coating",
        "graphene", "2d material", "semiconductor", "nanoparticle",
        "self-assembl", "soft matter", "functional materials"],
    "Separations and membranes": [
        "membrane", "gas separation", "adsorb", "adsorption", "sorbent",
        "filtration", "distillation", "chromatograph", "ion exchange",
        "desalinat", "solvent extraction"],
    "Manufacturing": [
        "advanced manufactur", "additive manufactur", "3d printing",
        "fabrication", "roll-to-roll", "process intensification", "scale-up",
        "smart manufactur", "biomanufactur", "process control"],
    "Artificial intelligence and machine learning": [
        "machine learning", "deep learning", "neural network",
        "artificial intelligence", "data-driven", "autonomous experiment",
        "digital twin", "surrogate model", "high-throughput screening"],
    "Quantum science": [
        "quantum computing", "quantum material", "quantum sensing",
        "quantum information", "quantum chemistry"],
    "Biology and biotechnology": [
        "biotechnology", "microbial", "synthetic biology", "enzyme",
        "bioreactor", "metabolic engineering", "fermentation", "biocataly",
        "biopolymer", "biomaterial", "bioprocess", "cell culture",
        "protein engineering", "genome"],
    "Environmental science": [
        "environmental remediation", "pollution", "emissions", "bioremediation",
        "air quality", "contaminant", "ecosystem", "circular economy",
        "recycling", "upcycling"],
    "Water": [
        "water treatment", "wastewater", "drinking water", "desalinat",
        "water purification", "water resources", "water quality"],
    "Public health": [
        "clinical trial", "drug delivery", "therapeutic", "pharmaceutical",
        "vaccine", "diagnostic", "medical countermeasure"],
    "Infectious disease": [
        "antibiotic", "antimicrobial", "pathogen", "infection", "antifungal",
        "antiviral", "biosurveillance"],
    "Climate change": [
        "climate change", "greenhouse gas", "global warming", "climate resilience"],
    "Space and aeronautics": [
        "aerospace", "spacecraft", "aeronautic", "propulsion",
        "in situ resource", "lunar", "planetary"],
}

BRIDGE_THEMES: list[dict] = [
    {"label": "CO₂ conversion and utilization",
     "domains": ["Catalysis and reaction engineering", "Carbon management"],
     "terms": ["co2 utilization", "co2 conversion", "co2 reduction",
               "carbon utilization", "e-fuels", "fuels from co2", "co2 hydrogenation"]},
    {"label": "Data-driven catalyst discovery",
     "domains": ["Artificial intelligence and machine learning",
                 "Catalysis and reaction engineering"],
     "terms": ["catalyst discovery", "catalyst screening", "machine learning",
               "high-throughput", "autonomous"]},
    {"label": "AI for materials discovery",
     "domains": ["Artificial intelligence and machine learning", "Materials science"],
     "terms": ["materials discovery", "materials genome", "autonomous experiment",
               "materials acceleration", "inverse design"]},
    {"label": "Carbon capture materials",
     "domains": ["Separations and membranes", "Carbon management"],
     "terms": ["carbon capture", "direct air capture", "co2 separation",
               "capture sorbent", "point-source capture"]},
    {"label": "Electrochemical energy conversion",
     "domains": ["Energy", "Catalysis and reaction engineering"],
     "terms": ["electrolysis", "electrolyzer", "fuel cell", "electrocataly",
               "hydrogen production"]},
    {"label": "Energy storage materials",
     "domains": ["Energy", "Materials science"],
     "terms": ["battery", "energy storage", "solid-state electrolyte",
               "electrode material"]},
    {"label": "Biomaterials and biomanufacturing",
     "domains": ["Biology and biotechnology", "Materials science"],
     "terms": ["biomaterial", "biomanufactur", "biopolymer", "bioprocess",
               "tissue engineering", "bioink"]},
    {"label": "Sustainable polymers and plastics upcycling",
     "domains": ["Materials science", "Environmental science"],
     "terms": ["plastic", "upcycling", "recycling", "circular economy",
               "biodegradable", "depolymerization"]},
    {"label": "Smart and digital manufacturing",
     "domains": ["Manufacturing", "Artificial intelligence and machine learning"],
     "terms": ["digital twin", "smart manufacturing", "process optimization",
               "advanced manufacturing", "cyber-physical"]},
    {"label": "Environmental biotechnology",
     "domains": ["Biology and biotechnology", "Environmental science"],
     "terms": ["bioremediation", "wastewater", "antimicrobial resistance",
               "microbiome", "environmental microbial"]},
    {"label": "Water treatment and separations",
     "domains": ["Separations and membranes", "Environmental science"],
     "terms": ["water treatment", "desalination", "pfas", "contaminant removal",
               "water reuse"]},
]

# Open-scope BAAs and omnibus calls often contain only administrative text.
# This small hand-checked map contributes the weakest signal and is used only
# when the record is recognizably open-scope; every such result is visibly
# flagged for verification in the UI.
AGENCY_SCOPE: list[dict] = [
    {"label": "Office of Naval Research / Navy labs",
     "pattern": "office of naval research|naval research lab|nswc|navsea|\\bonr\\b",
     "domains": ["Materials science", "Energy", "Manufacturing",
                 "Artificial intelligence and machine learning"]},
    {"label": "Army research (ARL / ARO / DEVCOM / ERDC)",
     "pattern": "army research (?:laboratory|office)|devcom|"
                "army combat capabilities|acc apg|"
                "engineer research and development|\\berdc\\b|\\baro\\b|\\barl\\b",
     "domains": ["Materials science", "Energy", "Manufacturing",
                 "Artificial intelligence and machine learning", "Environmental science"]},
    {"label": "Air Force research (AFOSR / AFRL)",
     "pattern": "air force (?:office of scientific research|research laboratory)|"
                "afosr|afrl",
     "domains": ["Materials science", "Energy", "Manufacturing",
                 "Artificial intelligence and machine learning", "Space and aeronautics"]},
    {"label": "DARPA", "pattern": "\\bdarpa\\b|defense advanced research",
     "domains": ["Materials science", "Manufacturing", "Energy",
                 "Artificial intelligence and machine learning", "Biology and biotechnology"]},
    {"label": "DOE Office of Science / ARPA-E",
     "pattern": "office of science|arpa-e|advanced research projects agency - energy|"
                "national energy technology|golden field office",
     "domains": ["Energy", "Materials science", "Catalysis and reaction engineering",
                 "Carbon management", "Artificial intelligence and machine learning",
                 "Quantum science", "Biology and biotechnology",
                 "Separations and membranes"]},
    {"label": "NASA", "pattern": "\\bnasa\\b",
     "domains": ["Space and aeronautics", "Materials science", "Energy",
                 "Manufacturing", "Artificial intelligence and machine learning"]},
]

BROAD_PATTERN = (
    r"broad agency announcement|\bbaa\b|continuation of solicitation|"
    r"office of science financial assistance|long[\s-]?range|"
    r"research announcement|\broses\b|omnibus|unsolicited proposal|"
    r"open topic|financial assistance program"
)

# These catalog facets are useful for browsing, but too broad to explain or
# materially boost a researcher match. In particular, a single noisy
# "Materials science" tag caused the Egypt Annual Program Statement to be
# recommended to most of the department.
_UMBRELLA_TOPICS = {
    "Artificial intelligence and machine learning",
    "Biology and biotechnology",
    "Energy",
    "Environmental science",
    "Manufacturing",
    "Materials science",
}


def _pi_domains(profile: dict) -> list[str]:
    """Program topics a PI works in, inferred from their OpenAlex topics, recent
    titles, and key phrases via :data:`DOMAIN_LEXICON`."""
    text = " ".join(
        (profile.get("topics") or [])
        + (profile.get("recent_titles") or [])
        + _key_terms(profile)
    ).lower()
    return [area for area, kws in DOMAIN_LEXICON.items()
            if any(k in text for k in kws)]


def _domains_for(name: str, profile: dict) -> list[str]:
    """Curated program-topic domains if we have them (the norm), otherwise fall
    back to the auto lexicon for any faculty not yet hand-curated."""
    if name in FACULTY_DOMAINS:
        return list(FACULTY_DOMAINS[name])
    return _pi_domains(profile)


def _niche_topics(catalog: list[dict]) -> set[str]:
    """Retain topic-frequency metadata for diagnostics and compatibility.

    Topic rarity no longer determines eligibility; the former rule mistakenly
    treated a noisy Materials science tag as sufficient research evidence.
    """
    from collections import Counter
    freq: Counter = Counter()
    for r in catalog:
        for x in (r.get("topic_areas") or []):
            freq[x] += 1
    cutoff = max(45, round(0.03 * len(catalog)))
    return {t for t, c in freq.items() if c <= cutoff}


def _best_url(r: dict) -> str:
    for k in ("funding_opportunity_url", "primary_document_url", "detail_page", "url"):
        u = r.get(k) or ""
        if re.match(r"^https?://", str(u), re.I):
            return str(u)
    return ""


def _deadline_text(r: dict) -> str:
    cd = r.get("close_date")
    if cd and re.match(r"^\d{4}-\d{2}-\d{2}$", str(cd)):
        return "Closes " + str(cd)
    return str(r.get("deadline_note") or r.get("close_date_note") or "")


def _listing_date(r: dict) -> str:
    """The date an opportunity was listed by its source or first seen here."""
    for key in ("posted_date", "source_first_seen_date"):
        value = str(r.get(key) or "")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value
    return ""


def _listing_date_value(value: str) -> int:
    return int(value.replace("-", "")) if re.match(r"^\d{4}-\d{2}-\d{2}$", value or "") else 0


def _recency_score(value: str, newest_value: str) -> float:
    """Return a bounded 0-3 recency contribution over a one-year window."""
    try:
        age = max(0, (date.fromisoformat(newest_value) - date.fromisoformat(value)).days)
    except (TypeError, ValueError):
        return 0.0
    return round(3.0 * max(0.0, 1.0 - age / 365.0), 3)


def match_to_catalog(profiles: list[dict], catalog_path: str, out_path: str,
                     top_n: int = 25) -> dict:
    """Match every PI against the catalog and emit a per-PI index the team page
    uses to compute mutual interests for any chosen subset.

    At least one focused research concept must match an opportunity. Catalog
    topics may corroborate that evidence but never establish eligibility by
    themselves. A bounded recency contribution is then combined with research
    relevance so newer calls are favored without outranking a substantially
    better scientific fit merely because of date.
    """
    catalog = [
        record
        for record in _load_catalog(catalog_path)
        if not record.get("status") or record_is_current(record)[0]
    ]
    niche = _niche_topics(catalog)

    # Roster = the full FACULTY list, so hand-curated people with no OpenAlex
    # profile are still included. Curated key terms / domains
    # take precedence; OpenAlex only supplies resolved_name / works_count.
    prof_by_name = {p.get("name"): p for p in profiles if p.get("name")}
    faculty_meta: dict[str, dict] = {}
    faculty_terms: dict[str, list[str]] = {}
    faculty_doms: dict[str, set] = {}
    for name in FACULTY:
        p = prof_by_name.get(name) or {"name": name}
        terms = _key_terms(p)
        doms = set(_domains_for(name, p))
        if not terms and not doms:
            continue
        resolved = name if p.get("error") else (p.get("resolved_name") or name)
        faculty_terms[name] = terms
        faculty_doms[name] = doms
        faculty_meta[name] = {
            "resolved_name": resolved,
            "openalex_id": None if p.get("error") else p.get("openalex_id"),
            "works_count": None if p.get("error") else p.get("works_count"),
            "research_summary": FACULTY_RESEARCH_SUMMARIES.get(name, ""),
            "key_terms": terms,
            "domains": sorted(doms),
        }
    term_sig = {name: [(t, _sig_words(t)) for t in terms]
                for name, terms in faculty_terms.items()}

    pi_matches: dict[str, list] = {name: [] for name in faculty_meta}
    # opp_id -> [(name, tier, relevance_score, rank_score), ...]
    per_opp: dict[str, list] = {}
    newest_listing = max(
        (_listing_date(opp) for opp in catalog),
        key=_listing_date_value,
        default="",
    )

    for opp in catalog:
        title = opp.get("title") or ""
        text = " ".join([
            title, opp.get("description") or "",
            " ".join(opp.get("disciplines") or []),
        ]).lower()
        opp_tokens = [w for w in _WORD_RE.findall(text) if w not in _STOP]
        if not opp_tokens:
            continue
        opp_topics = set(opp.get("topic_areas") or [])
        oid = (opp.get("opportunity_id") or opp.get("opportunity_number")
               or title)
        display = {
            "id": oid, "title": title, "agency": opp.get("agency") or "",
            "url": _best_url(opp), "deadline": _deadline_text(opp),
            "listing_date": _listing_date(opp),
        }
        for name, sigs in term_sig.items():
            doms = faculty_doms[name]
            hit_terms = [t for (t, sig) in sigs
                         if _phrase_hit(sig, opp_tokens)]
            if not hit_terms:
                continue
            shared = sorted((doms & opp_topics) - _UMBRELLA_TOPICS)
            relevance_score = round(
                4.0 * len(hit_terms) + min(1.5, 0.25 * len(shared)), 3
            )
            recency_score = _recency_score(display["listing_date"], newest_listing)
            rank_score = round(relevance_score + recency_score, 3)
            pi_matches[name].append({
                **display, "tier": "focused", "terms": hit_terms,
                "shared_topics": shared, "score": relevance_score,
                "relevance_score": relevance_score,
                "recency_score": recency_score,
                "rank_score": rank_score,
            })
            per_opp.setdefault(oid, []).append(
                (name, "focused", relevance_score, rank_score)
            )

    for name in pi_matches:
        pi_matches[name].sort(key=lambda m: (
            -m["rank_score"], -_listing_date_value(m["listing_date"]),
            -m["relevance_score"], (m["title"] or "").lower()))

    # Department-wide overview: opportunities where 2+ faculty have focused
    # concept evidence. Combined fit and recency determine order.
    idx = {m["id"]: m for lst in pi_matches.values() for m in lst}
    groups = []
    for oid, members in per_opp.items():
        if len({m[0] for m in members}) < 2:
            continue
        d = idx.get(oid, {})
        team = []
        for (name, tier, score, rank_score) in members:
            mm = next((x for x in pi_matches[name] if x["id"] == oid), {})
            team.append({"name": name, "tier": tier, "score": score,
                         "rank_score": rank_score,
                         "matched_terms": mm.get("terms") or [],
                         "shared_topics": mm.get("shared_topics") or []})
        team.sort(key=lambda t: (-t["rank_score"], -t["score"], t["name"]))
        groups.append({
            "opportunity_id": oid, "title": d.get("title") or oid,
            "agency": d.get("agency") or "", "url": d.get("url") or "",
            "deadline": d.get("deadline") or "",
            "listing_date": d.get("listing_date") or "",
            "team_size": len(team),
            "total_score": sum(t["score"] for t in team),
            "total_rank_score": round(sum(t["rank_score"] for t in team), 3),
            "suggested_team": team[:12],
        })
    groups.sort(key=lambda g: (
        -g["total_rank_score"], -_listing_date_value(g["listing_date"]),
        -g["team_size"], -g["total_score"], (g["title"] or "").lower()))

    out = {
        "catalog_size": len(catalog),
        "niche_topics": sorted(niche),
        "faculty": faculty_meta,
        "pi_matches": pi_matches,
        "multi_pi_suggestions": groups,
        "theme_lexicon": THEME_LEXICON,
        "bridge_themes": BRIDGE_THEMES,
        "agency_scope": AGENCY_SCOPE,
        "broad_pattern": BROAD_PATTERN,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("/* Generated by scripts/faculty_match.py. Do not edit by hand. */\n")
        fh.write("globalThis.FACULTY_MATCHES=")
        json.dump(out, fh, ensure_ascii=False)
        fh.write(";\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("profiles")
    p1.add_argument("--out", default="faculty_profiles.json")
    p2 = sub.add_parser("match")
    p2.add_argument("--catalog", default="data/opportunities.js")
    p2.add_argument("--profiles", default="faculty_profiles.json")
    p2.add_argument("--out", default="data/faculty_matches.js")
    args = ap.parse_args()

    if args.cmd == "profiles":
        profiles = build_profiles()
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(profiles, fh, ensure_ascii=False, indent=2)
        print(f"wrote {args.out} ({len(profiles)} faculty)")
    elif args.cmd == "match":
        profiles = json.load(open(args.profiles, encoding="utf-8"))
        out = match_to_catalog(profiles, args.catalog, args.out)
        print(f"wrote {args.out}: {len(out['multi_pi_suggestions'])} multi-PI suggestions")


if __name__ == "__main__":
    main()
