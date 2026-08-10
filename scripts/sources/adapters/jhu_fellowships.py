"""Johns Hopkins RDT fellowship repositories (graduate / postdoc / early-career).

JHU's Research Development & Translation team maintains three continuously
updated spreadsheets of student and early-career funding, organized by audience.
Each sub-page links to an .xlsx (currently via a bit.ly). We ride on their
curation to fill the fellowship buckets our federal Grants.gov catalog doesn't
cover (GRFP, NDSEG, Hertz, Ford, foundation fellowships, ...).

Staying current: the adapter scrapes each sub-page for its current spreadsheet
link every run and downloads it fresh, so it tracks JHU's updates automatically
rather than a one-time static import.

Avoiding duplicates / mess:
- Each row is audience-tagged via ``applicant_types`` (Graduate students /
  Postdoctoral researchers / Early-career faculty), so items land in the
  fellowship buckets rather than flooding the default view.
- On the *early-career faculty* sheet (the one that overlaps our federal catalog
  most — CAREER, NIH ESI, etc.) federal sponsors are dropped, keeping only the
  foundation/private awards we don't already have.
- The merge layer still lets Grants.gov win and drops same-id repeats.

The production adapter retries transient failures, falls back to the official
short links published by JHU, and accepts a refresh only when all three audience
workbooks parse above conservative row-count bounds. Otherwise the source
lifecycle retains its last-known-good snapshot.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import re
import time
import urllib.request
from typing import Iterable, Optional

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import USER_AGENT
from ..registry import register

SHEETS = [
    {"audience": "grad",
     "page": "https://research.jhu.edu/rdt/funding-opportunities/graduate/",
     "fallback_sheet": "https://bit.ly/GradFundingOpps7126",
     "applicant_types": ["Graduate students"], "drop_federal": False},
    {"audience": "postdoc",
     "page": "https://research.jhu.edu/rdt/funding-opportunities/postdoctoral/",
     "fallback_sheet": "https://bit.ly/PostdocFundingOpps7126",
     "applicant_types": ["Postdoctoral researchers"], "drop_federal": False},
    {"audience": "faculty",
     "page": "https://research.jhu.edu/rdt/funding-opportunities/early-career/",
     "fallback_sheet": "https://bit.ly/ECFopps7126",
     "applicant_types": ["Early-career faculty"], "drop_federal": True},
]

MIN_ROWS_PER_AUDIENCE = 50
FETCH_ATTEMPTS = 3

_FEDERAL_RE = re.compile(
    r"national science foundation|\bnsf\b|national institutes of health|\bnih\b"
    r"|department of energy|\bdoe\b|department of defense|\bdod\b|\bdarpa\b"
    r"|\bnasa\b|department of agriculture|\busda\b|\bepa\b|\bnist\b|\bnoaa\b"
    r"|office of naval research|air force|army research|\bnih\b|\bneh\b|\bnea\b"
    r"|department of education|\bnnsa\b|\barpa",
    re.IGNORECASE,
)

_MONEY_RE = re.compile(r"\$\s?([\d][\d,]{2,})(?:\s?(million|m|k))?", re.IGNORECASE)
_DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
)
_LINK_RE = re.compile(r"""https?://[^\s"'<>]+""", re.IGNORECASE)


def _clean_url(target: Optional[str], fallback: str) -> str:
    """Salvage a real http(s) URL from a cell hyperlink; JHU sheets sometimes
    carry mangled Outlook-cache paths with an embedded URL."""
    if not target:
        return fallback
    text = str(target)
    idx = text.lower().find("http")
    if idx == -1:
        return fallback
    url = text[idx:].strip()
    url = re.sub(r"^(https?):/(?!/)", r"\1://", url)   # fix "http:/x" -> "http://x"
    return url if "." in url else fallback


def _money(value) -> Optional[str]:
    if not value:
        return None
    m = _MONEY_RE.search(str(value))
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    scale = (m.group(2) or "").lower()
    if scale in ("million", "m"):
        n *= 1_000_000
    elif scale == "k":
        n *= 1_000
    return str(int(n))


def _first_date(value) -> Optional[str]:
    if not value:
        return None
    m = _DATE_RE.search(str(value))
    return m.group(1) if m else None


def _clean_deadline(value) -> Optional[str]:
    """JHU deadline cells are recurring/annual, often with a stale year (or a
    real date object). Render date cells as a month/day recurrence hint so they
    don't read as an expired hard deadline; pass through free text as-is."""
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        value = value.date()
    if isinstance(value, _dt.date):
        return "Recurring ~" + value.strftime("%b %d").replace(" 0", " ") + " (verify current year)"
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:300] or None


def _colmap(header_cells: list) -> dict:
    """Map each JHU column to a field by header keyword."""
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(header_cells):
        h = str(raw or "").strip().lower()
        if not h:
            continue
        if h.startswith("sponsor"):
            mapping.setdefault("sponsor", idx)
        elif h.startswith("program"):
            mapping.setdefault("program", idx)
        elif h.startswith("description"):
            mapping.setdefault("description", idx)
        elif "eligibility" in h:
            mapping.setdefault("eligibility", idx)
        elif "citizenship" in h:
            mapping.setdefault("citizenship", idx)
        elif "keyword" in h or "discipline" in h:
            mapping.setdefault("keywords", idx)
        elif "amount" in h:
            mapping.setdefault("amount", idx)
        elif "annual deadline" in h:
            mapping.setdefault("annual_deadline", idx)
        elif "deadline" in h:
            mapping.setdefault("deadline", idx)
    return mapping


def parse_worksheet(ws, cfg: dict) -> list[dict]:
    """Turn one JHU worksheet into opportunity dicts (dependency-light; the
    caller passes an openpyxl worksheet)."""
    # Find the header row (the one containing "Sponsor").
    header_row = None
    header_cells = []
    for r in range(1, 9):
        cells = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if any(str(v or "").strip().lower().startswith("sponsor") for v in cells):
            header_row, header_cells = r, cells
            break
    if header_row is None:
        return []
    cols = _colmap(header_cells)
    if "program" not in cols or "sponsor" not in cols:
        return []

    def cell(r, key):
        c = cols.get(key)
        return ws.cell(r, c + 1).value if c is not None else None

    out: list[dict] = []
    for r in range(header_row + 1, ws.max_row + 1):
        program = cell(r, "program")
        sponsor = cell(r, "sponsor")
        if not program or not str(program).strip():
            continue
        program = re.sub(r"\s+", " ", str(program)).strip()
        sponsor = re.sub(r"\s+", " ", str(sponsor or "")).strip()
        if cfg["drop_federal"] and sponsor and _FEDERAL_RE.search(sponsor):
            continue  # already covered by our Grants.gov catalog

        link = None
        prog_col = cols.get("program")
        if prog_col is not None:
            link = getattr(ws.cell(r, prog_col + 1), "hyperlink", None)
            link = getattr(link, "target", None)
        url = _clean_url(link, cfg["page"])

        eligibility = cell(r, "eligibility")
        citizenship = cell(r, "citizenship")
        elig_text = " ".join(
            str(x).strip() for x in (eligibility, citizenship) if x and str(x).strip()
        ) or None
        keywords = cell(r, "keywords")
        deadline_text = cell(r, "deadline") or cell(r, "annual_deadline")

        external_id = "jhu-{}-{}".format(
            cfg["audience"],
            hashlib.sha1(f"{sponsor}|{program}".casefold().encode()).hexdigest()[:16],
        )
        out.append({
            "title": program,
            "external_id": external_id,
            "url": url,
            "agency": sponsor or "Johns Hopkins RDT list",
            "description": (str(cell(r, "description")).strip()
                            if cell(r, "description") else None),
            "eligibility_text": elig_text,
            "applicant_types": list(cfg["applicant_types"]),
            "disciplines": [str(keywords).strip()] if keywords and str(keywords).strip() else [],
            "award_ceiling": _money(cell(r, "amount")),
            # JHU deadlines are recurring/annual with stale years -> keep as a note,
            # never a hard close_date (a past date would mark items expired and hide them).
            "close_date": None,
            "deadline_note": _clean_deadline(deadline_text),
        })
    return out


class JHUFellowshipsAdapter(SourceAdapter):
    slug = "jhu-fellowships"
    display_name = "Johns Hopkins RDT fellowships list"
    source_type = "Fellowship"
    enabled = True           # parser verified on JHU sample files; live fetch runs in pipeline
    min_records = 150
    max_records = 1500

    def fetch(self):
        """Download every JHU workbook or fail the source as an incomplete run.

        JHU intermittently rejects automated page requests.  The page remains
        the preferred source of the current workbook URL, while the official
        bit.ly link printed on that page is a resilient fallback.  A partial
        result must never replace the last-known-good three-audience snapshot.
        """
        results = []
        failures = []
        for cfg in SHEETS:
            candidates = []
            page_error = None
            try:
                html = self._get(cfg["page"]).decode("utf-8", errors="replace")
                links = _LINK_RE.findall(html)
                candidate = next(
                    (u for u in links
                     if "bit.ly" in u.lower() and "opp" in u.lower()), None)
                candidate = candidate or next(
                    (u for u in links if u.lower().endswith(".xlsx")), None)
                if candidate:
                    candidates.append(candidate)
            except Exception as exc:  # page fallback is intentional
                page_error = f"page: {type(exc).__name__}: {exc}"
            fallback = cfg.get("fallback_sheet")
            if fallback and fallback not in candidates:
                candidates.append(fallback)

            sheet_errors = []
            for candidate in candidates:
                try:
                    data = self._get(candidate)
                    if not data.startswith(b"PK"):
                        raise ValueError("response is not an XLSX/ZIP workbook")
                    results.append({**cfg, "data": data, "sheet_url": candidate})
                    break
                except Exception as exc:
                    sheet_errors.append(
                        f"{candidate}: {type(exc).__name__}: {exc}"
                    )
            else:
                details = [page_error, *sheet_errors]
                failures.append(
                    f"{cfg['audience']} ({'; '.join(item for item in details if item)})"
                )
        self.diagnostics = {
            "expected_audiences": [cfg["audience"] for cfg in SHEETS],
            "downloaded_audiences": [cfg["audience"] for cfg in results],
            "download_failures": failures,
        }
        if failures or len(results) != len(SHEETS):
            raise RuntimeError("Incomplete JHU workbook refresh: " + " | ".join(failures))
        return results

    @staticmethod
    def _get(url: str) -> bytes:
        last_error = None
        for attempt in range(FETCH_ATTEMPTS):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.read(16 * 1024 * 1024)  # 16 MB cap
            except Exception as exc:
                last_error = exc
                if attempt + 1 < FETCH_ATTEMPTS:
                    time.sleep(attempt + 1)
        raise RuntimeError(
            f"request failed after {FETCH_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        import openpyxl
        seen: set[str] = set()
        parsed = []
        audience_counts = {}
        for cfg in payload or []:
            wb = openpyxl.load_workbook(io.BytesIO(cfg["data"]), data_only=True)
            items = parse_worksheet(wb.active, cfg)
            audience_counts[cfg["audience"]] = len(items)
            if len(items) < MIN_ROWS_PER_AUDIENCE:
                self.diagnostics = {
                    **getattr(self, "diagnostics", {}),
                    "parsed_rows_by_audience": audience_counts,
                }
                raise ValueError(
                    f"JHU {cfg['audience']} workbook yielded only {len(items)} rows; "
                    f"expected at least {MIN_ROWS_PER_AUDIENCE}."
                )
            for item in items:
                if item["external_id"] in seen:
                    continue
                seen.add(item["external_id"])
                parsed.append(self._to_canonical(item))
        expected = {cfg["audience"] for cfg in SHEETS}
        if set(audience_counts) != expected:
            raise ValueError(
                "JHU parse did not receive every audience: "
                + ", ".join(sorted(expected - set(audience_counts)))
            )
        self.diagnostics = {
            **getattr(self, "diagnostics", {}),
            "parsed_rows_by_audience": audience_counts,
            "parsed_records": len(parsed),
        }
        return parsed

    def parse_file(self, path: str, cfg: dict) -> list[CanonicalOpportunity]:
        """Offline test helper: parse a local .xlsx against a sheet config."""
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        return [self._to_canonical(i) for i in parse_worksheet(wb.active, cfg)]

    @staticmethod
    def _to_canonical(item: dict) -> CanonicalOpportunity:
        return CanonicalOpportunity(
            title=item["title"],
            external_id=item.get("external_id"),
            url=item.get("url"),
            agency=item.get("agency"),
            description=item.get("description"),
            eligibility_text=item.get("eligibility_text"),
            applicant_types=item.get("applicant_types") or [],
            disciplines=item.get("disciplines") or [],
            award_ceiling=item.get("award_ceiling"),
            close_date=item.get("close_date"),
            deadline_note=item.get("deadline_note"),
        )


register(JHUFellowshipsAdapter())
