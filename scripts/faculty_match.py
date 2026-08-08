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
ROCHESTER_HINT = "rochester"

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
    """Best OpenAlex author for a name, preferring a Rochester affiliation."""
    data = _get(f"{OPENALEX}/authors?search={urllib.parse.quote(name)}&per_page=10")
    results = data.get("results") or []
    if not results:
        return None
    rochester = [a for a in results
                 if ROCHESTER_HINT in _affiliation_names(a).lower()]
    pool = rochester or results
    # Highest works_count in the preferred pool.
    best = max(pool, key=lambda a: a.get("works_count") or 0)
    best["_matched_rochester"] = bool(rochester)
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
            profiles.append({"name": name, "error": "no OpenAlex match"})
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
_STOP = set("""the and for with from this that are was into over out per via
research program grants grant funding award awards project projects support
science engineering national university institute department studies study
development new using based their which will been more also may can under""".split())


def _load_catalog(path: str) -> list[dict]:
    text = open(path, encoding="utf-8").read()
    start = text.index("{")
    obj = json.loads(text[start:].rstrip().rstrip(";"))
    return obj.get("opportunities", obj.get("records", []))


def _bag(*parts: str) -> set[str]:
    words = set()
    for p in parts:
        for w in _WORD_RE.findall((p or "").lower()):
            if w not in _STOP:
                words.add(w)
    return words


def _profile_bag(profile: dict) -> set[str]:
    return _bag(" ".join(profile.get("concepts", [])),
               " ".join(profile.get("topics", [])),
               " ".join(profile.get("recent_titles", [])))


def match_to_catalog(profiles: list[dict], catalog_path: str, out_path: str,
                     top_n: int = 25) -> dict:
    catalog = _load_catalog(catalog_path)
    # Build a research bag from each profile's concepts + topics + recent titles.
    # OpenAlex retired the author ``x_concepts`` field, so most profiles now carry
    # an empty ``concepts`` list; gate on the *combined* bag being non-empty rather
    # than on ``concepts`` specifically (otherwise every faculty is skipped).
    bags: dict[str, set] = {}
    for p in profiles:
        if p.get("error"):
            continue
        bag = _profile_bag(p)
        if bag:
            bags[p["name"]] = bag
    per_faculty: dict[str, list] = {name: [] for name in bags}
    per_opp_scores: list[tuple] = []

    for opp in catalog:
        obag = _bag(opp.get("title"), opp.get("description"),
                    " ".join(opp.get("topic_areas") or []),
                    " ".join(opp.get("disciplines") or []))
        if not obag:
            continue
        opp_id = opp.get("opportunity_id") or opp.get("opportunity_number") or opp.get("title")
        contributors = []
        for name, fbag in bags.items():
            overlap = fbag & obag
            score = len(overlap)
            if score >= 3:
                contributors.append((name, score, sorted(overlap)[:8]))
                per_faculty[name].append((score, opp_id, opp.get("title")))
        if len(contributors) >= 2:  # multi-PI candidate
            per_opp_scores.append((sum(c[1] for c in contributors), opp_id,
                                   opp.get("title"), contributors))

    faculty_top = {
        name: [{"opportunity_id": oid, "title": t, "score": s}
               for (s, oid, t) in sorted(items, reverse=True)[:top_n]]
        for name, items in per_faculty.items()
    }
    multi_pi = [{
        "opportunity_id": oid, "title": t, "total_score": tot,
        "suggested_team": [{"name": n, "score": s, "shared_terms": terms}
                           for (n, s, terms) in sorted(contribs, key=lambda c: -c[1])[:4]],
    } for (tot, oid, t, contribs) in sorted(per_opp_scores, reverse=True)[:100]]

    out = {"faculty_top_matches": faculty_top, "multi_pi_suggestions": multi_pi}
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
