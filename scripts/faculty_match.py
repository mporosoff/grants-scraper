"""Phase 4 engine: ChemE faculty publication profiles + solicitation matching.

Two stages:

1. ``build_profiles`` — for each Chemical & Sustainability Engineering faculty
   member, resolve their OpenAlex author record (preferring University of
   Rochester affiliation) and build a research profile from their top OpenAlex
   concepts/topics and recent publication titles. Writes ``faculty_profiles.json``.
   OpenAlex is free and needs no key; we pass a mailto for the polite pool.

2. ``match_to_catalog`` — score every opportunity in ``data/opportunities.js``
   against each faculty profile by topic/keyword overlap, and emit
   ``data/faculty_matches.js`` for the (forthcoming) internal team-match page,
   including simple multi-PI groupings for large/center solicitations.

Stage 1 is runnable now (network only). Stage 2 is implemented but expects the
catalog file; it is wired for the pipeline but intentionally conservative (v1
keyword/topic overlap; embeddings are a later upgrade).

Usage:
    python -m scripts.faculty_match profiles --out faculty_profiles.json
    python -m scripts.faculty_match match --catalog data/opportunities.js \
        --profiles faculty_profiles.json --out data/faculty_matches.js
"""

from __future__ import annotations

import argparse
import json
import re
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
    University of Rochester. Returns None when no confident UR match exists, so
    we omit the person rather than attach a same-named stranger's publications
    (that mis-resolution is how "Gang Fan" and "Melodie Lawton" went wrong)."""
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
support science sciences engineering technology technologies national university
universities institute department departments studies study development
applications application advancing advanced approaches approach based using their
which will been more also may can under new toward towards related general
foundation opportunity opportunities proposal proposals faculty investigator
investigators""".split())

# Hand-curated research interests per PI, verified against each person's
# University of Rochester ChemE faculty page and recent publications. These are
# authoritative: they override OpenAlex's auto topics, which mis-resolved several
# people (a computer-scientist "David Foster", a fungal biologist "Astrid Muller",
# a perovskite "Gang Fan") and attached over-broad tags. Phrases are specific on
# purpose so a match rests on real overlap, never a generic word.
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
# ``topic_areas`` vocabulary. Chosen conservatively and only where central to the
# person's work -- a broad umbrella tag (Energy, Environmental science, AI/ML) is
# assigned only when it is genuinely a core area, never inferred from one stray
# keyword. These drive niche-topic and broad-solicitation matching.
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


def _load_catalog(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as catalog_file:
        text = catalog_file.read()
    start = text.index("{")
    obj = json.loads(text[start:].rstrip().rstrip(";"))
    return obj.get("opportunities", obj.get("records", []))


def _sig_words(phrase: str) -> list[str]:
    return [w for w in _WORD_RE.findall((phrase or "").lower()) if w not in _STOP]


def _phrase_hit(sig: list[str], opp_words: set[str],
                common: set | None = None) -> bool:
    """A key phrase 'hits' an opportunity when enough of its distinctive words are
    present. A single-word phrase needs its one word; multi-word phrases need at
    least ceil(60%) of their distinctive words (minimum 2), so a match can't rest
    on one or two generic words like 'energy' + 'materials'.

    ``common`` is an optional set of corpus-frequent words (e.g. 'materials',
    'learning', 'systems') that carry no distinguishing signal; they are stripped
    before the count so an OpenAlex topic label like 'Machine Learning in
    Materials Science' can't match hundreds of unrelated notices."""
    orig_len = len(sig)
    if common:
        sig = [w for w in sig if w not in common]
    if not sig:
        return False
    present = sum(1 for w in sig if w in opp_words)
    if orig_len == 1:
        return present >= 1          # a genuine single-word key term
    # A multi-word phrase must keep >=2 distinctive words, so it can't collapse to
    # one lingering moderately-common word (e.g. 'sustainable process design' ->
    # 'sustainable') and match hundreds of unrelated notices.
    if len(sig) < 2:
        return False
    need = max(2, (3 * len(sig) + 4) // 5)   # ceil(0.6 * len), floored at 2
    return present >= need


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
# Program-topic domains. A PI's *specific* work ("heterogeneous catalysis") is
# mapped onto the catalog's controlled ``topic_areas`` vocabulary. Broad
# solicitations (BAAs, DOE Office of Science, NASA ROSES) bury their real scope
# behind boilerplate FOA language, but they ARE tagged with these program
# topics -- so matching on topics, not just wording, is what surfaces them.
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

# Concrete markers of a broad/open solicitation (vs. a targeted call). These
# fund many topics, so we let a PI's program-topic overlap surface them -- but
# they are flagged "broad" so the reader verifies fit against the full notice.
_BROAD_RE = re.compile(
    r"broad agency announcement|\bbaa\b|continuation of solicitation|"
    r"office of science|long[\s-]?range|research announcement|\broses\b|"
    r"omnibus|unsolicited proposal",
    re.I,
)


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


def _is_broad(opp: dict) -> bool:
    blob = (opp.get("title") or "") + " " + (opp.get("description") or "")[:400]
    return bool(_BROAD_RE.search(blob))


def _niche_topics(catalog: list[dict]) -> set[str]:
    """Topic areas specific enough that a single shared one signals a real
    research overlap. Common umbrella topics (Energy, AI/ML, Environmental
    science...) are excluded -- those only count toward *broad* solicitations,
    so they can't flood the results."""
    from collections import Counter
    freq: Counter = Counter()
    for r in catalog:
        for x in (r.get("topic_areas") or []):
            freq[x] += 1
    cutoff = max(45, round(0.03 * len(catalog)))
    return {t for t, c in freq.items() if c <= cutoff}


def _common_words(catalog: list[dict]) -> set:
    """Words that appear in more than ~5% of notices carry no distinguishing
    signal (e.g. 'materials', 'learning', 'systems', 'energy'). Stripping them
    from phrase matching keeps a match resting on genuinely specific terms."""
    from collections import Counter
    df: Counter = Counter()
    for opp in catalog:
        text = " ".join([
            opp.get("title") or "", opp.get("description") or "",
            " ".join(opp.get("topic_areas") or []),
            " ".join(opp.get("disciplines") or []),
        ]).lower()
        for w in {w for w in _WORD_RE.findall(text) if w not in _STOP}:
            df[w] += 1
    cutoff = max(60, round(0.05 * len(catalog)))
    return {w for w, c in df.items() if c > cutoff}


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


def match_to_catalog(profiles: list[dict], catalog_path: str, out_path: str,
                     top_n: int = 25) -> dict:
    """Match every PI against the catalog and emit a per-PI index the team page
    uses to compute mutual interests for any chosen subset.

    Distinctive phrase/niche-topic matches and open-solicitation topic matches
    are both eligible. The signal type remains as provenance, but it does not
    create separate result categories or outrank a newer listing.
    """
    catalog = _load_catalog(catalog_path)
    niche = _niche_topics(catalog)
    common = _common_words(catalog)

    # Roster = the full FACULTY list, so hand-curated people with no OpenAlex
    # profile (Bhalode, Lawton) are still included. Curated key terms / domains
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
            "key_terms": terms,
            "domains": sorted(doms),
        }
    term_sig = {name: [(t, _sig_words(t)) for t in terms]
                for name, terms in faculty_terms.items()}

    pi_matches: dict[str, list] = {name: [] for name in faculty_meta}
    per_opp: dict[str, list] = {}     # opp_id -> [(name, tier, score), ...]

    for opp in catalog:
        title = opp.get("title") or ""
        text = " ".join([
            title, opp.get("description") or "",
            " ".join(opp.get("topic_areas") or []),
            " ".join(opp.get("disciplines") or []),
        ]).lower()
        opp_words = {w for w in _WORD_RE.findall(text) if w not in _STOP}
        if not opp_words:
            continue
        opp_topics = set(opp.get("topic_areas") or [])
        broad = _is_broad(opp)
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
                         if _phrase_hit(sig, opp_words, common)]
            niche_hit = sorted(doms & opp_topics & niche)
            broad_hit = sorted(doms & opp_topics) if broad else []
            strong = bool(hit_terms or niche_hit)
            if not strong and not broad_hit:
                continue
            tier = "strong" if strong else "broad"
            shared = niche_hit if strong else broad_hit
            score = (2 if strong else 0) + len(hit_terms) + len(shared)
            pi_matches[name].append({
                **display, "tier": tier, "terms": hit_terms,
                "shared_topics": shared, "score": score,
            })
            per_opp.setdefault(oid, []).append((name, tier, score))

    for name in pi_matches:
        pi_matches[name].sort(key=lambda m: (
            -_listing_date_value(m["listing_date"]),
            -m["score"], (m["title"] or "").lower()))

    # Department-wide overview: opportunities where 2+ faculty overlap, newest
    # listings first. Fit counts and scores only break same-date ties.
    idx = {m["id"]: m for lst in pi_matches.values() for m in lst}
    groups = []
    for oid, members in per_opp.items():
        if len({m[0] for m in members}) < 2:
            continue
        d = idx.get(oid, {})
        team = []
        for (name, tier, score) in members:
            mm = next((x for x in pi_matches[name] if x["id"] == oid), {})
            team.append({"name": name, "tier": tier, "score": score,
                         "matched_terms": mm.get("terms") or [],
                         "shared_topics": mm.get("shared_topics") or []})
        team.sort(key=lambda t: -t["score"])
        groups.append({
            "opportunity_id": oid, "title": d.get("title") or oid,
            "agency": d.get("agency") or "", "url": d.get("url") or "",
            "deadline": d.get("deadline") or "",
            "listing_date": d.get("listing_date") or "",
            "team_size": len(team),
            "total_score": sum(t["score"] for t in team),
            "suggested_team": team[:12],
        })
    groups.sort(key=lambda g: (
        -_listing_date_value(g["listing_date"]), -g["team_size"],
        -g["total_score"], (g["title"] or "").lower()))

    out = {
        "catalog_size": len(catalog),
        "niche_topics": sorted(niche),
        "faculty": faculty_meta,
        "pi_matches": pi_matches,
        "multi_pi_suggestions": groups,
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
