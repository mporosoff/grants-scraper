"""
scrape_faculty.py
Scrapes core faculty from the UR Department of Chemical and Sustainability
Engineering and writes a structured profile for each one.

Legacy note: this script is retained only as a reference. The product direction
now uses faculty-authored research profiles entered through the web application.

Run it:
    pip install requests beautifulsoup4
    python legacy/scrape_faculty.py

Outputs:
    faculty.json  -- full structured records
    faculty.csv   -- same thing, spreadsheet friendly

Design note: this deliberately does NOT depend on CSS class names, because
university CMS templates get re-skinned without warning. It anchors on the
profile-page URL pattern instead, which is far more stable.
"""

import csv
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.hajim.rochester.edu/che/people/faculty/index.html"

# Faculty profile links look like /che/people/faculty/<slug>/index.html
PROFILE_RE = re.compile(r"/che/people/faculty/[^/]+/index\.html$")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[-.\s]?\d{4}")
OFFICE_RE = re.compile(r"\b\d{3,4}[A-Z]?\s+(?:Wegmans|Gavett|Hopeman|Goergen)\s+Hall\b", re.I)

HEADERS = {
    # Be a polite citizen. Identify the scraper and give a contact.
    "User-Agent": "URochester-ChemE-GrantMatch/0.1 (marc.porosoff@rochester.edu)"
}

# Rank -> normalized career stage. Order matters: check longest phrases first.
RANK_PATTERNS = [
    ("Assistant Research Professor", "assistant_research"),
    ("Associate Research Professor", "associate_research"),
    ("Research Professor", "research_professor"),
    ("Assistant Professor", "assistant"),
    ("Associate Professor", "associate"),
    ("Distinguished Professor", "full"),
    ("Professor", "full"),
    ("Lecturer", "lecturer"),
    ("Instructor", "lecturer"),
]

# Titles that indicate a teaching-track appointment. These people are usually
# not the target for research grants, so we flag rather than delete them and
# let you decide.
NON_RESEARCH_MARKERS = ("instructional", "(instruction", "teaching track")

# Career-stage eligibility hints used later when matching against grants.
EARLY_CAREER_STAGES = {"assistant", "assistant_research"}


def fetch(url):
    """GET a page with a timeout and a clear error if it fails."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        print(f"  ! could not fetch {url}: {exc}", file=sys.stderr)
        return None


def find_profile_links(html, base_url):
    """Return an ordered, de-duplicated list of (name, absolute_url)."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not PROFILE_RE.search(href):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        # Skip nav links that point at the listing page itself.
        if absolute.rstrip("/") == base_url.rstrip("/"):
            continue
        label = anchor.get_text(" ", strip=True)
        if not label:
            continue
        seen.add(absolute)
        found.append((label, absolute))

    return found


def normalize_name(raw):
    """'Porosoff, Marc D.' -> ('Marc D. Porosoff', 'Porosoff')"""
    raw = re.sub(r"\s+", " ", raw).strip()
    if "," in raw:
        last, first = raw.split(",", 1)
        return f"{first.strip()} {last.strip()}", last.strip()
    parts = raw.split()
    return raw, parts[-1] if parts else raw


def parse_titles(block_text):
    """Pull every line that reads like an academic title."""
    titles = []
    for line in block_text.splitlines():
        line = line.strip(" *_")
        if not line or len(line) > 160:
            continue
        if re.search(r"\b(Professor|Lecturer|Instructor|Scientist|Chair|Director)\b", line):
            # Skip the labeled contact fields.
            if line.lower().startswith(("office", "telephone", "email", "web address")):
                continue
            titles.append(line)
    # De-duplicate, preserve order.
    return list(dict.fromkeys(titles))


def derive_career_stage(titles):
    joined = " ; ".join(titles)
    for phrase, stage in RANK_PATTERNS:
        if phrase.lower() in joined.lower():
            return stage
    return "unknown"


def is_research_active(titles):
    joined = " ; ".join(titles).lower()
    return not any(marker in joined for marker in NON_RESEARCH_MARKERS)


def extract_interests(block_text):
    """
    Grab everything after the 'Interests:' label up to a blank line.
    Returns a list of individual interest terms.
    """
    match = re.search(r"Interests?\s*:\s*(.+?)(?:\n\s*\n|\Z)", block_text, re.S | re.I)
    if not match:
        return []
    raw = re.sub(r"\s+", " ", match.group(1)).strip()
    # The site uses semicolons as the separator, but not always consistently.
    parts = [p.strip(" .;") for p in re.split(r"[;\n]", raw)]
    # Drop empties and collapse duplicates (the live page has at least one
    # interest listed twice).
    cleaned = []
    for part in parts:
        if part and part.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(part)
    return cleaned


def parse_profile(name_label, url):
    """Fetch one faculty profile page and build a record."""
    html = fetch(url)
    if html is None:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Strip nav, header, and footer so their text does not pollute the fields.
    for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()

    main = soup.find("main") or soup.find(id="main") or soup.body or soup
    text = main.get_text("\n", strip=True)

    full_name, last_name = normalize_name(name_label)
    titles = parse_titles(text)

    emails = [e for e in EMAIL_RE.findall(text) if "rochester.edu" in e.lower()]
    phones = PHONE_RE.findall(text)
    offices = OFFICE_RE.findall(text)

    # Personal or group website, i.e. an external link that is not a UR page.
    group_site = None
    for anchor in main.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("http") and "rochester.edu" not in href:
            if any(skip in href for skip in ("facebook", "twitter", "linkedin",
                                             "youtube", "instagram", "tiktok",
                                             "googletagmanager", "threads")):
                continue
            group_site = href
            break

    interests = extract_interests(text)
    stage = derive_career_stage(titles)

    return {
        "name": full_name,
        "last_name": last_name,
        "profile_url": url,
        "titles": titles,
        "career_stage": stage,
        "early_career_eligible_hint": stage in EARLY_CAREER_STAGES,
        "research_active": is_research_active(titles),
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "office": offices[0] if offices else None,
        "group_website": group_site,
        "interests": interests,
        "interests_count": len(interests),
        # This is the flag that matters. An empty profile cannot be matched
        # against anything, so it needs a publication-based backfill.
        "needs_publication_backfill": len(interests) < 3,
        "joint_appointments": [t for t in titles
                               if "Laser Energetics" in t
                               or "Biomedical" in t
                               or "Microbiology" in t
                               or "Chemistry" in t],
    }


def main():
    print(f"Fetching listing: {LISTING_URL}")
    listing_html = fetch(LISTING_URL)
    if listing_html is None:
        sys.exit("Could not load the faculty listing page. Check the URL.")

    links = find_profile_links(listing_html, LISTING_URL)
    print(f"Found {len(links)} faculty profile links.\n")

    if not links:
        sys.exit(
            "No profile links matched. The URL pattern probably changed.\n"
            "Inspect the page source and update PROFILE_RE."
        )

    records = []
    for i, (label, url) in enumerate(links, 1):
        print(f"[{i}/{len(links)}] {label}")
        record = parse_profile(label, url)
        if record:
            records.append(record)
            flags = []
            if not record["research_active"]:
                flags.append("teaching track")
            if record["needs_publication_backfill"]:
                flags.append("THIN PROFILE")
            suffix = f"  <- {', '.join(flags)}" if flags else ""
            print(f"      {record['career_stage']}, "
                  f"{record['interests_count']} interests{suffix}")
        time.sleep(1)  # Be gentle with the server.

    with open("faculty.json", "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    csv_columns = ["name", "career_stage", "research_active",
                   "needs_publication_backfill", "email", "office",
                   "group_website", "interests_count", "interests",
                   "titles", "profile_url"]
    with open("faculty.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["interests"] = "; ".join(record["interests"])
            row["titles"] = " | ".join(record["titles"])
            writer.writerow(row)

    research = [r for r in records if r["research_active"]]
    thin = [r for r in research if r["needs_publication_backfill"]]

    print(f"\n{'-' * 55}")
    print(f"Total scraped:        {len(records)}")
    print(f"Research active:      {len(research)}")
    print(f"Thin profiles:        {len(thin)}")
    for r in thin:
        print(f"   - {r['name']} ({r['interests_count']} interests)")
    print("\nWrote faculty.json and faculty.csv")


if __name__ == "__main__":
    main()
