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

# Optional hand-curated key phrases per PI (override the auto OpenAlex topics).
# Leave a name out to use their topics. Example:
#   FACULTY_KEYTERMS = {"Marc D. Porosoff": ["CO2 hydrogenation", "tungsten carbide",
#       "reverse water-gas shift", "syngas to olefins", "heterogeneous catalysis"]}
FACULTY_KEYTERMS: dict[str, list[str]] = {}


def _load_catalog(path: str) -> list[dict]:
    text = open(path, encoding="utf-8").read()
    start = text.index("{")
    obj = json.loads(text[start:].rstrip().rstrip(";"))
    return obj.get("opportunities", obj.get("records", []))


def _sig_words(phrase: str) -> list[str]:
    return [w for w in _WORD_RE.findall((phrase or "").lower()) if w not in _STOP]


def _phrase_hit(sig: list[str], opp_words: set[str]) -> bool:
    """A key phrase 'hits' an opportunity when enough of its distinctive words are
    present. A single-word phrase needs its one word; multi-word phrases need at
    least ceil(60%) of their distinctive words (minimum 2), so a match can't rest
    on one or two generic words like 'energy' + 'materials'."""
    if not sig:
        return False
    present = sum(1 for w in sig if w in opp_words)
    if len(sig) == 1:
        return present >= 1
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


def match_to_catalog(profiles: list[dict], catalog_path: str, out_path: str,
                     top_n: int = 25) -> dict:
    catalog = _load_catalog(catalog_path)

    # Each PI is reduced to 5-8 descriptive key phrases; an opportunity matches a
    # PI only when it shares the *distinctive* words of one of those phrases. This
    # is far more specific than the old whole-word-bag overlap.
    faculty_terms: dict[str, list[str]] = {}
    faculty_meta: dict[str, dict] = {}
    for p in profiles:
        if p.get("error"):
            continue
        terms = _key_terms(p)
        if not terms:
            continue
        faculty_terms[p["name"]] = terms
        faculty_meta[p["name"]] = {
            "resolved_name": p.get("resolved_name") or p["name"],
            "openalex_id": p.get("openalex_id"),
            "works_count": p.get("works_count"),
            "key_terms": terms,
        }
    term_sig = {name: [(t, _sig_words(t)) for t in terms]
                for name, terms in faculty_terms.items()}

    per_faculty: dict[str, list] = {name: [] for name in faculty_terms}
    per_opp_scores: list[tuple] = []

    for opp in catalog:
        text = " ".join([
            opp.get("title") or "", opp.get("description") or "",
            " ".join(opp.get("topic_areas") or []),
            " ".join(opp.get("disciplines") or []),
        ]).lower()
        opp_words = {w for w in _WORD_RE.findall(text) if w not in _STOP}
        if not opp_words:
            continue
        opp_id = opp.get("opportunity_id") or opp.get("opportunity_number") or opp.get("title")
        contributors = []
        for name, sigs in term_sig.items():
            matched = [t for (t, sig) in sigs if _phrase_hit(sig, opp_words)]
            if matched:
                contributors.append((name, len(matched), matched))
                per_faculty[name].append((len(matched), opp_id, opp.get("title"), matched))
        if len(contributors) >= 2:  # multi-PI candidate
            per_opp_scores.append((sum(c[1] for c in contributors), opp_id,
                                   opp.get("title"), contributors))

    def _rank(item):
        return (-(item[0]), (item[2] or "").lower())

    faculty_top = {
        name: [{"opportunity_id": oid, "title": t, "score": s, "matched_terms": m}
               for (s, oid, t, m) in sorted(items, key=_rank)[:top_n]]
        for name, items in per_faculty.items()
    }
    # Select groups so every PI is represented -- a niche PI (e.g. Shestopalov)
    # must not be starved by a global top-N cut -- then rank by total score.
    ranked = sorted(per_opp_scores, key=lambda x: -x[0])
    chosen: dict = {}
    seen_per_pi: dict = {}
    for entry in ranked:                       # each PI's strongest ~12 groups
        for (n, _s, _m) in entry[3]:
            if seen_per_pi.get(n, 0) < 12:
                seen_per_pi[n] = seen_per_pi.get(n, 0) + 1
                chosen[entry[1]] = entry
    for entry in ranked[:120]:                 # plus the strongest groups overall
        chosen[entry[1]] = entry
    multi_pi = [{
        "opportunity_id": oid, "title": t, "total_score": tot,
        # Include *every* contributing PI (capped generously) so a low-scoring
        # member is never silently dropped from a team they belong to.
        "suggested_team": [{"name": n, "score": s, "matched_terms": m}
                           for (n, s, m) in sorted(contribs, key=lambda c: -c[1])[:12]],
    } for (tot, oid, t, contribs) in sorted(chosen.values(), key=lambda x: -x[0])]

    out = {"faculty": faculty_meta,
           "faculty_top_matches": faculty_top,
           "multi_pi_suggestions": multi_pi}
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
