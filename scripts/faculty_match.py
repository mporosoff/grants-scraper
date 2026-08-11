"""ChemE faculty roster + research-interest data for the team collaboration finder.

This module is the single source of truth for WHO is matched and WHAT they work
on. It exports a static data file (``data/faculty_matches.js``) containing:

  * each PI's hand-curated research interests and program-topic domains
    (verified against UR faculty pages and publications),
  * the theme lexicon (expansion vocabulary per domain),
  * bridge themes (recognized complementary domain pairs),
  * an agency scope map for open-scope solicitations (BAAs and omnibus calls
    whose notices carry no subject words at all).

ALL matching happens live in the browser (``team_match.html``) against the
nightly-refreshed catalog, so this file only needs regenerating when the
faculty roster or interests change -- never for new opportunities.

Usage:
    python -m scripts.faculty_match profiles --out faculty_profiles.json
        (optional; refreshes OpenAlex names/publication counts)
    python -m scripts.faculty_match match --out data/faculty_matches.js
        (writes the static data file; --profiles is optional)
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

OPENALEX = "https://api.openalex.org"
MAILTO = "marc.porosoff@rochester.edu"           # OpenAlex polite pool
ROCHESTER_HINT = "university of rochester"        # exclude "Rochester Institute of Technology"

# Core Chemical & Sustainability Engineering faculty (Hajim, 2026).
FACULTY = [
    "Mitchell Anthamatten", "Yasemin Basdogan", "Pooja Rajendra Bhalode",
    "Siddharth Deshpande", "Gang Fan", "David G. Foster", "Melodie I. Lawton",
    "Darren Lipomi", "Allison J. Lopatkin", "Astrid M. Muller",
    "Marc D. Porosoff", "Alexander A. Shestopalov", "Wyatt E. Tenhaeff",
    "Matthew Z. Yates",
]

# --------------------------------------------------------------------------- #
# Hand-curated research interests per PI, verified against each person's
# University of Rochester ChemE faculty page and recent publications. These are
# authoritative: OpenAlex auto-topics mis-resolved several people (a
# computer-scientist "David Foster", a fungal biologist "Astrid Muller", a
# perovskite "Gang Fan") and attached over-broad tags. Phrases are specific on
# purpose so a match rests on real overlap, never a generic word.
# --------------------------------------------------------------------------- #
FACULTY_KEYTERMS: dict[str, list[str]] = {
    "Mitchell Anthamatten": [
        "liquid crystal polymers", "two-photon polymerization",
        "shape-memory polymers", "stimuli-responsive polymers",
        "polymer synthesis", "cellulose nanocrystal thin films"],
    "Yasemin Basdogan": [
        "computational chemistry", "machine learning for materials discovery",
        "CO2 separation membranes", "electrocatalytic oxidation",
        "molecular simulation", "solvation modeling"],
    "Pooja Rajendra Bhalode": [
        "process systems engineering", "multiscale molecules-to-systems modeling",
        "physics and data-driven hybrid modeling",
        "product-process lifecycle optimization", "sustainable process design",
        "particulate and process dynamics"],
    "Siddharth Deshpande": [
        "computational heterogeneous catalysis",
        "machine learning for catalyst screening", "oxygenate electrooxidation",
        "tungsten carbide catalysts", "propane dehydrogenation",
        "first-principles reaction modeling"],
    "Gang Fan": [
        "bio-inspired catalysis", "microbial and synthetic biology",
        "biodegradable polymers and plastic upcycling", "CO2 electroreduction",
        "bioelectrochemistry", "DNA-directed catalyst assembly"],
    "David G. Foster": [
        "transport phenomena", "computational fluid dynamics",
        "microfluidic cell capture", "nanoparticle coatings",
        "reactor modeling", "electrodeposition"],
    "Melodie I. Lawton": [
        "shape-memory polymers", "polymeric composites", "biomaterials",
        "polymer degradation", "controlled drug delivery",
        "structure-property relationships"],
    "Darren Lipomi": [
        "organic and flexible electronics", "conducting polymers",
        "stretchable semiconductors", "mechanical properties of organic electronics",
        "electrotactile haptics", "bioelectronic interfaces"],
    "Allison J. Lopatkin": [
        "antibiotic resistance", "plasmid dynamics and horizontal gene transfer",
        "microbial systems biology", "bacterial metabolism",
        "antimicrobial resistance in the environment", "quantitative microbiology"],
    "Astrid M. Muller": [
        "earth-abundant electrocatalysts", "electrocatalytic water oxidation",
        "CO2 reduction to syngas", "PFAS electrochemical destruction",
        "laser-ablation nanoparticle synthesis",
        "sustainable electrochemical manufacturing"],
    "Marc D. Porosoff": [
        "heterogeneous catalysis", "CO2 hydrogenation and utilization",
        "reverse water-gas shift", "tungsten carbide catalysts",
        "syngas-to-olefins", "Fischer-Tropsch synthesis"],
    "Alexander A. Shestopalov": [
        "surface functionalization and molecular monolayers",
        "soft lithography and contact printing", "micro- and nanofabrication",
        "atomic layer deposition", "organic thin-film coatings",
        "self-assembled monolayers"],
    "Wyatt E. Tenhaeff": [
        "lithium metal batteries", "solid electrolyte interphase",
        "battery interfacial engineering", "polymer thin-film electrolytes",
        "energy storage materials", "battery separators"],
    "Matthew Z. Yates": [
        "functional polymer coatings", "sorbent polymers for chemical sensing",
        "waveguide-enhanced Raman sensing", "electrochemical sensors",
        "bimetallic catalyst particles", "colloids and emulsions"],
}

# Curated program-topic domains per PI, drawn from the catalog's controlled
# ``topic_areas`` vocabulary. Assigned only where central to the person's work;
# umbrella tags (Energy, AI/ML, Environmental science) appear only when genuinely
# core, never inferred from one stray keyword.
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
    "Melodie I. Lawton": ["Materials science", "Biology and biotechnology"],
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

# --------------------------------------------------------------------------- #
# Theme lexicon: expansion vocabulary per program-topic domain. Terms are
# matched as substrings of the notice text (title + description + tags), so
# stems like "electrocataly" cover electrocatalyst/-ysis/-ytic. Keep every term
# >= 4 characters and specific -- these carry modest per-hit weight in the
# browser scorer, but sloppy entries here are how noise gets in.
# --------------------------------------------------------------------------- #
THEME_LEXICON: dict[str, list[str]] = {
    "Catalysis and reaction engineering": [
        "cataly", "electrocataly", "photocataly", "reaction engineering",
        "kinetics", "water-gas shift", "hydrogenation", "dehydrogenation",
        "reforming", "chemical conversion"],
    "Energy": [
        "energy conversion", "energy storage", "fuel cell", "biofuel",
        "battery", "batteries", "electrochem", "solar fuel", "photovolta",
        "combustion", "hydrogen production", "electroly", "renewable energy",
        "clean energy", "energy efficiency"],
    "Carbon management": [
        "carbon dioxide", "carbon capture", "carbon utiliz", "decarboniz",
        "sequestrat", "direct air capture", "syngas", "co2 reduction",
        "co2 conversion", "negative emissions", "carbon-neutral"],
    "Materials science": [
        "advanced materials", "polymer", "nanomaterial", "thin film",
        "crystallin", "metal-organic framework", "composite", "coating",
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
        "quantum comput", "quantum material", "quantum sensing",
        "quantum information", "quantum chemistry"],
    "Biology and biotechnology": [
        "biotechnolog", "microb", "synthetic biology", "enzyme",
        "bioreactor", "metabolic engineering", "fermentation", "biocataly",
        "biopolymer", "biomaterial", "bioprocess", "cell culture",
        "protein engineering", "genome"],
    "Environmental science": [
        "environmental remediation", "pollut", "emission", "sustainab",
        "bioremediation", "air quality", "contaminant", "ecosystem",
        "circular economy", "recycl", "upcycl"],
    "Water": [
        "water treatment", "wastewater", "drinking water", "desalinat",
        "water purification", "water resources", "water quality"],
    "Public health": [
        "clinical", "drug delivery", "therapeutic", "pharmaceutic",
        "vaccine", "diagnostic", "medical countermeasure"],
    "Infectious disease": [
        "antibiotic", "antimicrobial", "pathogen", "infection",
        "antifungal", "antiviral", "biosurveillance"],
    "Climate change": [
        "climate", "greenhouse gas", "global warming", "climate resilien"],
    "Space and aeronautics": [
        "aerospace", "spacecraft", "aeronautic", "propulsion",
        "in situ resource", "lunar", "planetary"],
}

# --------------------------------------------------------------------------- #
# Bridge themes: recognized complementary domain pairs. When two DIFFERENT
# selected PIs bring the two sides, the pair becomes an active team theme with
# its own vocabulary -- this is how "catalysis person + ML person" surfaces
# data-driven catalyst discovery calls neither would rank alone.
# --------------------------------------------------------------------------- #
BRIDGE_THEMES: list[dict] = [
    {"label": "CO2 conversion & utilization",
     "domains": ["Catalysis and reaction engineering", "Carbon management"],
     "terms": ["co2 utiliz", "co2 conversion", "co2 reduction", "carbon utiliz",
               "e-fuels", "fuels from co2", "co2 hydrogenation"]},
    {"label": "Data-driven catalyst discovery",
     "domains": ["Artificial intelligence and machine learning",
                 "Catalysis and reaction engineering"],
     "terms": ["catalyst discovery", "catalyst screening", "machine learning",
               "high-throughput", "autonomous"]},
    {"label": "AI for materials discovery",
     "domains": ["Artificial intelligence and machine learning",
                 "Materials science"],
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
    {"label": "Biomaterials & biomanufacturing",
     "domains": ["Biology and biotechnology", "Materials science"],
     "terms": ["biomaterial", "biomanufactur", "biopolymer", "bioprocess",
               "tissue engineering", "bioink"]},
    {"label": "Sustainable polymers & plastics upcycling",
     "domains": ["Materials science", "Environmental science"],
     "terms": ["plastic", "upcycl", "recycl", "circular economy", "biodegrad",
               "depolymeriz"]},
    {"label": "Smart & digital manufacturing",
     "domains": ["Manufacturing",
                 "Artificial intelligence and machine learning"],
     "terms": ["digital twin", "smart manufactur", "process optimization",
               "advanced manufactur", "cyber-physical"]},
    {"label": "Environmental biotechnology",
     "domains": ["Biology and biotechnology", "Environmental science"],
     "terms": ["bioremediation", "wastewater", "antimicrobial resistance",
               "microbiome", "environmental microb"]},
    {"label": "Water treatment & separations",
     "domains": ["Separations and membranes", "Environmental science"],
     "terms": ["water treatment", "desalinat", "pfas", "contaminant removal",
               "water reuse"]},
]

# --------------------------------------------------------------------------- #
# Agency scope map for open-scope solicitations. Some BAAs and omnibus calls
# (ONR Long Range, Army DEVCOM/ARL) carry NO subject words in title, tags, or
# description -- pure administrative boilerplate -- so no text matching can
# find them. These agencies' broad announcements are included at modest weight
# (always flagged "broad - verify fit") when the team works in a listed domain.
# Patterns are matched case-insensitively against the record's agency name, and
# only applied to records that look like open-scope calls (broad_pattern).
# --------------------------------------------------------------------------- #
AGENCY_SCOPE: list[dict] = [
    {"label": "Office of Naval Research / Navy labs",
     "pattern": "office of naval research|naval research lab|nswc|navsea|\\bonr\\b",
     "domains": ["Materials science", "Energy", "Manufacturing",
                 "Artificial intelligence and machine learning"]},
    {"label": "Army research (ARL / ARO / DEVCOM / ERDC)",
     "pattern": "army research|devcom|army combat capabilities|acc apg|"
                "engineer research and development|\\berdc\\b|army -- materiel",
     "domains": ["Materials science", "Energy", "Manufacturing",
                 "Artificial intelligence and machine learning",
                 "Environmental science"]},
    {"label": "Air Force research (AFOSR / AFRL)",
     "pattern": "air force|afosr|afrl",
     "domains": ["Materials science", "Energy", "Manufacturing",
                 "Artificial intelligence and machine learning",
                 "Space and aeronautics"]},
    {"label": "DARPA",
     "pattern": "\\bdarpa\\b|defense advanced research",
     "domains": ["Materials science", "Manufacturing", "Energy",
                 "Artificial intelligence and machine learning",
                 "Biology and biotechnology"]},
    {"label": "DOE Office of Science / ARPA-E",
     "pattern": "office of science|arpa-e|advanced research projects agency - energy|"
                "national energy technology|golden field office",
     "domains": ["Energy", "Materials science",
                 "Catalysis and reaction engineering", "Carbon management",
                 "Artificial intelligence and machine learning",
                 "Quantum science", "Biology and biotechnology",
                 "Separations and membranes"]},
    {"label": "NASA",
     "pattern": "\\bnasa\\b",
     "domains": ["Space and aeronautics", "Materials science", "Energy",
                 "Manufacturing",
                 "Artificial intelligence and machine learning"]},
    {"label": "Defense health / medical research",
     "pattern": "defense health|usamraa|medical research acquisition",
     "domains": ["Public health", "Biology and biotechnology",
                 "Infectious disease"]},
    {"label": "DTRA",
     "pattern": "\\bdtra\\b|defense threat reduction",
     "domains": ["Materials science", "Biology and biotechnology",
                 "Environmental science"]},
]

# Markers of an open-scope solicitation (vs. a targeted call). Kept as a plain
# regex source string so the browser applies the identical definition.
BROAD_PATTERN = (
    r"broad agency announcement|\bbaa\b|continuation of solicitation|"
    r"office of science financial assistance|long[\s-]?range|"
    r"research announcement|\broses\b|omnibus|unsolicited proposal|"
    r"open topic|financial assistance program"
)


# --------------------------------------------------------------------------- #
# OpenAlex profile refresh (optional; supplies resolved names / works counts)
# --------------------------------------------------------------------------- #
def _get(url: str) -> dict:
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(
        f"{url}{sep}mailto={MAILTO}",
        headers={"User-Agent": f"Funding-Finder-FacultyMatch/1.0 ({MAILTO})"},
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
    University of Rochester; None when no confident UR match exists, so we
    omit publication counts rather than attach a same-named stranger's."""
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
            "topics": topics,
            "recent_titles": titles,
        })
        time.sleep(0.3)
    return profiles


# --------------------------------------------------------------------------- #
# Static data export -- the browser does all matching against the live catalog.
# --------------------------------------------------------------------------- #
def export_static(profiles_path: str | None, out_path: str) -> dict:
    prof_by_name: dict[str, dict] = {}
    if profiles_path:
        try:
            for p in json.load(open(profiles_path, encoding="utf-8")):
                if p.get("name"):
                    prof_by_name[p["name"]] = p
        except FileNotFoundError:
            pass  # profiles are optional; roster tables are authoritative

    faculty_meta: dict[str, dict] = {}
    for name in FACULTY:
        terms = FACULTY_KEYTERMS.get(name) or []
        doms = FACULTY_DOMAINS.get(name) or []
        if not terms and not doms:
            print(f"WARNING: {name} has no curated interests/domains; skipped")
            continue
        p = prof_by_name.get(name) or {}
        err = p.get("error")
        faculty_meta[name] = {
            "resolved_name": name if err else (p.get("resolved_name") or name),
            "openalex_id": None if err else p.get("openalex_id"),
            "works_count": None if err else p.get("works_count"),
            "key_terms": list(terms),
            "domains": sorted(doms),
        }

    out = {
        "schema": 2,
        "faculty": faculty_meta,
        "theme_lexicon": THEME_LEXICON,
        "bridge_themes": BRIDGE_THEMES,
        "agency_scope": AGENCY_SCOPE,
        "broad_pattern": BROAD_PATTERN,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("/* Generated by scripts/faculty_match.py. Do not edit by hand.\n")
        fh.write("   Static roster/lexicon only -- matching runs in the browser\n")
        fh.write("   against the live catalog, so this file only changes when\n")
        fh.write("   faculty or research interests change. */\n")
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
    p2.add_argument("--profiles", default="faculty_profiles.json")
    p2.add_argument("--out", default="data/faculty_matches.js")
    p2.add_argument("--catalog", default=None,
                    help="ignored (kept for compatibility); matching is client-side")
    args = ap.parse_args()

    if args.cmd == "profiles":
        profiles = build_profiles()
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(profiles, fh, ensure_ascii=False, indent=2)
        print(f"wrote {args.out} ({len(profiles)} faculty)")
    elif args.cmd == "match":
        out = export_static(args.profiles, args.out)
        print(f"wrote {args.out}: {len(out['faculty'])} faculty, "
              f"{len(out['theme_lexicon'])} theme domains, "
              f"{len(out['bridge_themes'])} bridge themes (static data; "
              "matching runs in the browser)")


if __name__ == "__main__":
    main()
