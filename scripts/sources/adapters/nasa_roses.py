"""NASA ROSES program elements — a `native` structured source (§18.1 D⅝ S1).

**This is a parse of NASA's own declared hierarchy, not an inference.** No
pattern family, no segmentation layer, no Cov4 classifier and no review queue is
involved: NASA publishes the program-element taxonomy as a table, and this
module reads it. Provenance is therefore `native` (§5.1).

Everything here was measured against the live source on 2026-08-17 and is
recorded in `docs/ROSES_SOURCE_INSPECTION.md`. Read that before changing a
selector.

**Emission boundary — the most important thing in this file.**
Table 3 holds 69 rows: 6 overview/container rows and 63 program elements. Only
**10** of those elements exist as Funding Finder catalog records today -- matched
on solicitation number, with normalised title as a weaker fallback. S1's scope is
deliberately narrow:

* the 10 matched elements yield authoritative ROSES relationship data
  (`subtopic_children`), and
* the other **53 are measured inventory only** (`standalone_inventory`), of which
  only **2 are currently open**.

The 53 are **not** emitted as catalog opportunities *by this module*. Ingesting
them is a catalog-expansion decision with dedup, precedence and §0.5
consequences. **That decision is now taken (§13 decision 13, 2026-08-18): it is
built as `Package N -- NASA ROSES Catalog Source`, which is separate work with
its own gate.** Until Package N lands, `parse()` returns nothing at all, which is
what keeps the inventory out of `opportunities.js` structurally rather than by
convention -- and the 2 currently open unmatched elements are a recorded
catalog-completeness gap.

The adapter also stays `enabled = False`: a new enabled source changes catalog
output with `--enable-subtopics` off, which §0.5 forbids.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import PoliteClient
from ..registry import register

# Stable entry point. The ROSES year, solicitation GUID, document id and
# amendment number are all DISCOVERED from here -- none is hard-coded, because
# every one of them turns over annually or on amendment.
SARA_SOLICITATIONS_URL = (
    "https://science.nasa.gov/researchers/sara/grant-solicitations/"
)
TABLE_LINK_RE = re.compile(
    r"https://solicitation\.nasaprs\.com/ROSES(\d{4})table(\d)", re.IGNORECASE
)

# Measured link kinds (docs/ROSES_SOURCE_INSPECTION.md §3). An overview row
# points at a repository PDF; a real element points at its own NSPIRES page.
OVERVIEW_LINK = "viewrepositorydocument"

# NASA's own status strings, exactly as they appear in the date columns.
NATIVE_NOT_SOLICITED = "not_solicited"
NATIVE_TBD = "tbd"
NATIVE_NO_DUE_DATE = "no_due_date"
NATIVE_FOLLOW_LINK = "follow_link"
NATIVE_DATED = "dated"
NATIVE_NONE = "no_date_given"          # the literal "N/A"
NATIVE_OVERVIEW = "overview"

# Derived, NOT native. NASA publishes no "closed" status; closure is inferred
# from the parsed dates and must be labelled as inferred wherever it is used.
DERIVED_OPEN = "open"
DERIVED_CLOSED = "closed"
DERIVED_UNDATED = "undated"

_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})")
_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")
_CELL_RE = re.compile(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>")
_HREF_RE = re.compile(r'href="([^"]+)"')
_AMEND_RE = re.compile(r"Amend[%\s_]*(\d+)", re.IGNORECASE)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", fragment)).strip()


def parse_dates(cell: str):
    """Every date in a cell, tolerant of the measured dirty formatting.

    `12/03 /2025`, `12/ 15 /2025` and `1/26/2026` all occur in the live source.
    """
    found = []
    for match in _DATE_RE.finditer(cell or ""):
        month, day, year = (int(part) for part in match.groups())
        try:
            found.append(_dt.date(year, month, day))
        except ValueError:                  # a malformed date is not a crash
            continue
    return found


def classify_native_status(date_cells, is_overview: bool) -> str:
    """NASA's own semantics. Never invents a status NASA does not publish."""
    if is_overview:
        return NATIVE_OVERVIEW
    joined = " ".join(date_cells).lower()
    if "not solicited" in joined:
        return NATIVE_NOT_SOLICITED
    if "no due date" in joined:
        return NATIVE_NO_DUE_DATE
    if "follow link" in joined:
        return NATIVE_FOLLOW_LINK
    if any(parse_dates(cell) for cell in date_cells):
        return NATIVE_DATED
    if "tbd" in joined:
        return NATIVE_TBD
    return NATIVE_NONE


def derive_currentness(element, today=None) -> str:
    """DERIVED, not native (§18.1 D⅝ S1). Kept separate on purpose.

    `No Due Date` is rolling submission and counts as open; a dated element is
    open until its last date passes. Everything else is undated -- not closed,
    because NASA has not said so.
    """
    today = today or _dt.date.today()
    status = element["native_status"]
    if status == NATIVE_NO_DUE_DATE:
        return DERIVED_OPEN
    if status != NATIVE_DATED:
        return DERIVED_UNDATED
    dates = [d for cell in element["due_date_cells"] for d in parse_dates(cell)]
    if not dates:
        return DERIVED_UNDATED
    return DERIVED_OPEN if max(dates) >= today else DERIVED_CLOSED


def parse_table(html: str) -> list[dict]:
    """Every Table 3 row, in NASA's appendix order, overview rows included.

    Order is preserved rather than sorted: appendix order *is* the hierarchy.
    """
    rows = []
    for position, match in enumerate(_ROW_RE.finditer(html or "")):
        fragment = match.group(1)
        cells = [_text(cell) for cell in _CELL_RE.findall(fragment)]
        if not cells or not cells[0]:
            continue
        if cells[0].strip().upper() == "APPENDIX":       # header
            continue
        hrefs = _HREF_RE.findall(fragment)
        url = hrefs[0].replace("&amp;", "&") if hrefs else None
        # Measured: 53 rows carry 4 cells and 17 carry 3, of which 16 colspan a
        # single status across both date columns and one simply omits a cell.
        date_cells = cells[2:] if len(cells) > 2 else []
        is_overview = bool(url and OVERVIEW_LINK in url)
        rows.append({
            "appendix_code": cells[0],
            "title": cells[1] if len(cells) > 1 else "",
            "due_date_cells": date_cells,
            # NASA's own wording, before any normalisation, including the
            # (Step-1)/(Mandatory NOI)/(Phase-1 via ARK RPS) qualifiers.
            "native_deadline_text": " | ".join(date_cells),
            "element_url": url,
            "is_overview": is_overview,
            "appendix_order": position,
            "division": cells[0].split(".")[0] if "." in cells[0] else cells[0],
            "amended": 'color="#ff0000"' in fragment.lower(),
        })
    for row in rows:
        row["native_status"] = classify_native_status(
            row["due_date_cells"], row["is_overview"]
        )
        # Identity is (code, title): the codes are neither contiguous nor
        # unique. `A.7` is absent from Table 3, and `D.3C` appears twice for
        # XRISM Type 1 and Type 2 sharing one solId.
        row["identity"] = (row["appendix_code"], row["title"])
    return rows


class NasaRosesAdapter(SourceAdapter):
    """ROSES program elements. Disabled; invokable directly for measurement."""

    slug = "nasa-roses"
    display_name = "NASA ROSES"
    source_type = "Federal"
    enabled = False                 # §0.5: enabling this changes catalog output
    min_records = 1
    max_records = 200

    # §7.4 canary floors, derived from the measured source rather than guessed.
    EXPECTED_DIVISIONS = ("A", "B", "C", "D", "E", "F")
    MEASURED_ELEMENT_COUNT = 63     # 2026-08-17, ROSES-2025 Amendment 69
    MIN_ELEMENTS = 40               # see check_health for the derivation
    MAX_CROSS_TABLE_DELTA = 5

    def __init__(self, client=None):
        super().__init__()
        # The opt-in is justified per source (§17.11): these hosts offer only
        # AES256-GCM-SHA384, which CPython's default cipher list omits.
        # Certificate and hostname verification remain on.
        self._client = client or PoliteClient(legacy_tls_ciphers=True)

    # --- discovery ------------------------------------------------------
    def discover_table_urls(self, landing_html=None) -> dict:
        """Resolve the authoritative ROSES tables from the stable SARA page."""
        html = landing_html
        if html is None:
            html = self._client.get_text(SARA_SOLICITATIONS_URL)
        found = {}
        for match in TABLE_LINK_RE.finditer(html):
            year, number = int(match.group(1)), match.group(2)
            # Highest year wins: the page lists prior cycles too.
            if number in found and found[number][0] >= year:
                continue
            found[number] = (year, match.group(0))
        if "3" not in found:
            raise RuntimeError(
                "No ROSES Table 3 link found on the SARA solicitations page; "
                "the discovery surface has changed (§7.4)."
            )
        return {
            "year": found["3"][0],
            "table3": found["3"][1],
            "table2": found["2"][1] if "2" in found else None,
        }

    def fetch(self):
        """Table 3 (substrate) plus Table 2 (corroboration only)."""
        discovered = self.discover_table_urls()
        table3 = self._client.get_text(discovered["table3"])
        table2 = None
        if discovered["table2"]:
            try:
                table2 = self._client.get_text(discovered["table2"])
            except Exception:               # noqa: BLE001 - health, not fatal
                table2 = None
        return {
            "year": discovered["year"],
            "table3_html": table3,
            "table2_html": table2,
            "amendment": self._amendment_of(table3),
        }

    @staticmethod
    def _amendment_of(html: str):
        match = _AMEND_RE.search(html or "")
        return int(match.group(1)) if match else None

    # --- parsing --------------------------------------------------------
    def rows(self, payload) -> list[dict]:
        return parse_table(payload["table3_html"])

    @staticmethod
    def split_rows(rows):
        """(overview/container rows, program elements)."""
        overview = [r for r in rows if r["is_overview"]]
        elements = [r for r in rows if not r["is_overview"]]
        return overview, elements

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        """**Deliberately empty. This is the S1 emission boundary.**

        The 53 program elements with no catalog record are *measured inventory*
        (`standalone_inventory`), not opportunities this module publishes.
        Emitting them is a catalog-expansion decision -- dedup against
        Grants.gov, source precedence, update ownership, catalog size, §0.5 --
        taken as §13 decision 13 and scheduled as `Package N`, which is separate
        work with its own gate. Returning nothing keeps them out of
        `opportunities.js` structurally, not by convention.
        """
        return []

    # --- the two S1 outputs ---------------------------------------------
    def standalone_inventory(self, rows, *, catalog_matches=()) -> list[dict]:
        """Program elements with no catalog record. Measured, never emitted."""
        matched = set(catalog_matches)
        _overview, elements = self.split_rows(rows)
        return [e for e in elements if e["identity"] not in matched]

    def subtopic_children(self, rows, *, parent_matches, as_of=None):
        """§5.1 `native` child records for elements that DO have a parent.

        `parent_matches` maps an element identity to the catalog
        `opportunity_id` it belongs to. Nothing is invented: every field comes
        from NASA's table.
        """
        _overview, elements = self.split_rows(rows)
        children = []
        for element in elements:
            parent = parent_matches.get(element["identity"])
            if not parent:
                continue
            children.append({
                "record_type": "subtopic",
                "parent_id": parent,
                "subtopic_code": element["appendix_code"],
                "title": element["title"],
                "subtopic_ordinal": element["appendix_order"],
                "subtopic_source": "native",          # §5.1 provenance ladder
                "segmentation_method": None,          # orthogonal, and unused
                "pattern_family": None,               # no family was involved
                "source_document_url": element["element_url"],
                "native_status": element["native_status"],
                "native_deadline_text": element["native_deadline_text"],
                "derived_currentness": derive_currentness(element),
                "division": element["division"],
                "amended": element["amended"],
                "first_seen": as_of,
                "last_verified": as_of,
            })
        return children

    # --- §7.4 health ----------------------------------------------------
    def check_health(self, payload, rows=None) -> dict:
        """Three canaries, measured rather than guessed. See §7.4.

        Ordered by how stable the thing being asserted is:

        1. **Six-division sentinel (primary).** ROSES always solicits across
           divisions A-F, each with an Overview element. This survives annual
           opening, closing and amendment, so a missing division means the
           parse or the source broke -- not that the cycle moved on.
        2. **Element floor (secondary).** Measured 63 elements at ROSES-2025
           Amendment 69. The floor is 40, deliberately far below: 15 elements
           were already `Not Solicited This Year` and a new cycle re-opens
           gradually, so a tight floor would fire every July. 40 still catches
           catastrophic shrinkage -- a partial parse yielding a handful of rows.
        3. **Cross-table check (tertiary).** Table 2 lists the same elements in
           date order. Equality is NOT required: `A.7` is a measured, legitimate
           discrepancy in NASA's own tables. A delta above
           MAX_CROSS_TABLE_DELTA is materially unexplained and warns.
        """
        rows = self.rows(payload) if rows is None else rows
        overview, elements = self.split_rows(rows)
        divisions = {r["division"] for r in rows}
        missing = [d for d in self.EXPECTED_DIVISIONS if d not in divisions]

        failures, warnings = [], []
        if missing:
            failures.append(
                f"division sentinel: missing {', '.join(missing)} of "
                f"{'/'.join(self.EXPECTED_DIVISIONS)}"
            )
        if len(elements) < self.MIN_ELEMENTS:
            failures.append(
                f"element floor: parsed {len(elements)}, floor "
                f"{self.MIN_ELEMENTS} (measured {self.MEASURED_ELEMENT_COUNT})"
            )

        cross = None
        if payload.get("table2_html"):
            table2 = parse_table(payload["table2_html"])
            _o2, elements2 = self.split_rows(table2)
            cross = abs(len(elements2) - len(elements))
            if cross > self.MAX_CROSS_TABLE_DELTA:
                warnings.append(
                    f"cross-table: Table 2 has {len(elements2)} elements, "
                    f"Table 3 has {len(elements)} (delta {cross} > "
                    f"{self.MAX_CROSS_TABLE_DELTA})"
                )
        else:
            warnings.append("cross-table: Table 2 unavailable, check skipped")

        return {
            "healthy": not failures,
            "failures": failures,
            "warnings": warnings,
            "rows": len(rows),
            "overview_rows": len(overview),
            "program_elements": len(elements),
            "divisions": sorted(divisions),
            "cross_table_delta": cross,
            "amendment": payload.get("amendment"),
            "year": payload.get("year"),
        }


register(NasaRosesAdapter())
