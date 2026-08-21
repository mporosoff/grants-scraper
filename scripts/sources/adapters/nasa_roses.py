"""NASA ROSES program elements — a `native` structured source (§18.1 D⅝ S1).

**This is a parse of NASA's own declared hierarchy, not an inference.** No
pattern family, no segmentation layer, no Cov4 classifier and no review queue is
involved: NASA publishes the program-element taxonomy as a table, and this
module reads it. Provenance is therefore `native` (§5.1).

Everything here was measured against the live source on 2026-08-17 and is
recorded in `docs/ROSES_SOURCE_INSPECTION.md`. Read that before changing a
selector.

**Two outputs, two packages, one parser.**

*P6.1 (subtopics).* `subtopic_children` returns `native`-provenance child records
for elements that already have a catalog parent. Unchanged by P8.

*P8 (catalog source).* `parse()` emits **standalone catalog opportunities for
actionable unmatched elements only**, which is DEC-13. Every refresh re-reads the
whole published inventory and decides again, so an element enters the catalog when
it becomes actionable and stays out while it is inactive, past, TBD or
`Not Solicited This Year` -- with no human follow-up (§18.1 P8.4).

**Emission requires the catalog.** `parse()` cannot know what is already published
unless the merge tells it, so it emits **nothing** without a `catalog_records`
context (`set_context`, §18.1 P8.1). That is deliberate fail-closed behaviour: a
caller that forgets the context gets zero records, never duplicates.

**Reconciliation is deterministic and uses no fuzzy title matching** (§18.1 P8.2).
Measured against the committed catalog: exactly 10 records carry an
`NNH<yy>ZDA<nnn>[A-Z]-` opportunity number, all 10 embed their appendix code in the
title, and matching on that code alone reproduces P6.1d's 63/10/53 split exactly.

**Two identities, and only one of them can be ambiguous.** Native ROSES identity is
`(cycle, appendix_code, program_title)` and always distinguishes two rows, because
NASA gives them different titles. The *cross-source* key is the appendix code alone,
and that is the one a repeated code breaks. So a duplicate code suppresses an element
**only when a catalog record also carries that code** -- otherwise both rows are
ordinary unmatched elements, each publishable on its own currentness. Measured:
`D.3C` is the only repeated code, no catalog record carries it, and both of its rows
are past their date today.

The adapter also stays `enabled = False`: a new enabled source changes catalog
output with `--enable-subtopics` off, which §0.5 forbids.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Iterable
from urllib.parse import unquote

import hashlib

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

# --- cross-source identity (§18.1 P8.2), measured, not assumed -------------
# A catalog record that represents a ROSES element announces it two ways, and both
# were verified against every one of the 10 matched records in the committed
# catalog: the solicitation number, and the appendix code printed in the title.
#
#   NNH25ZDA001N-ATMOS        "ROSES25: A.14 Atmosphere"
#   NNH25ZDA001N-RRNES        "ROSES 2025: A.4 Rapid Response and Novel Research…"
#
# Both are exact string forms. There is deliberately **no** fuzzy-title matching:
# a normalised-title comparison is the framework's existing last-resort collision
# test in `merge_records`, not this module's identity rule.
ROSES_SOLICITATION_RE = re.compile(r"^\s*NNH(\d{2})ZDA\d{3}[A-Z]", re.IGNORECASE)
CATALOG_CODE_RE = re.compile(
    r"ROSES[\s-]*(?:20)?(\d{2})\s*:\s*([A-F]\.\d+[A-Z]?)\b", re.IGNORECASE
)
# The solicitation number is only published in Table 3 for the handful of rows
# that carry a short link or a solNum link (measured: 4 + 2 of 69). It is read
# when present and left empty otherwise -- never synthesised.
SHORT_LINK_RE = re.compile(
    r"solicitation\.nasaprs\.com/(NNH\d{2}ZDA\d{3}[A-Z][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)
SOLNUM_PARAM_RE = re.compile(r"solNum=([A-Za-z0-9_-]+)", re.IGNORECASE)


class RosesReconciliationError(RuntimeError):
    """Raised when the inventory cannot be reconciled safely, so nothing is emitted.

    Routed through the registry's per-adapter isolation, which means the source is
    marked unhealthy and its last-known-good snapshot is retained -- previously
    published NASA records survive an ambiguity instead of being deleted by it
    (§18.1 P8.5 case 6).
    """


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


def _counts(values) -> dict:
    """Deterministic {value: count}, sorted, for diagnostics."""
    tally: dict = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return dict(sorted(tally.items()))


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


def cycle_of(year) -> str:
    """Two-digit ROSES cycle, e.g. 2025 -> "25". The cycle is part of identity."""
    return f"{int(year) % 100:02d}"


def element_solicitation_number(element: dict):
    """The solicitation number **as published**, or None. Never synthesised."""
    url = element.get("element_url") or ""
    match = SHORT_LINK_RE.search(url) or SOLNUM_PARAM_RE.search(url)
    return match.group(1).upper() if match else None


def _title_fingerprint(title: str) -> str:
    seed = re.sub(r"[^a-z0-9]+", " ", (title or "").casefold()).strip()
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def element_external_id(element: dict, year) -> str:
    """Stable per-element id: cycle + appendix code + title fingerprint.

    Three properties, each required by §18.1 P8.2:

    * **distinct for same code, different title** -- `D.3C` occurs twice in the
      measured source (XRISM Type 1 and Type 2), so the code alone is not a key;
      NASA's own identity is `(code, title)`.
    * **stable across ordinary updates** -- a changed due date, a changed status or
      an amendment flag does not touch either component, so a re-run re-identifies
      the same element rather than minting a second one.
    * **cycle-scoped** -- ROSES-2026 re-soliciting the same programme is a new
      opportunity with a new deadline, exactly as Grants.gov treats it.
    """
    return (
        f"{cycle_of(year)}-{element['appendix_code'].upper()}"
        f"-{_title_fingerprint(element['title'])}"
    )


def catalog_roses_index(records) -> dict:
    """Index the catalog's existing ROSES records by ``(cycle, appendix code)``.

    Returns ``{"by_code": {(cycle, code): [ids]}, "unresolved": [...]}``.
    ``unresolved`` holds records that announce themselves as ROSES through their
    solicitation number but whose appendix code cannot be parsed -- an ambiguity
    that must fail closed rather than risk a duplicate.
    """
    by_code: dict = {}
    unresolved: list = []
    for record in records or []:
        number = str(record.get("opportunity_number") or "")
        title = str(record.get("title") or "")
        number_match = ROSES_SOLICITATION_RE.match(number)
        code_match = CATALOG_CODE_RE.search(title)
        if not number_match and not code_match:
            continue
        identity = str(record.get("opportunity_id") or number or title)
        if code_match:
            key = (
                f"{int(code_match.group(1)) % 100:02d}",
                code_match.group(2).upper(),
            )
            by_code.setdefault(key, []).append(identity)
        else:
            unresolved.append(
                {
                    "opportunity_id": identity,
                    "opportunity_number": number,
                    "title": title[:120],
                    "reason": "roses_number_without_parseable_appendix_code",
                }
            )
    return {"by_code": by_code, "unresolved": unresolved}


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
    #: Enabled by P8. This adds *catalog* records, which is the package's purpose;
    #: it does not touch `--enable-subtopics`, and §8.4's hermetic gate selects
    #: `--adapter sample`, so §0.5's artifacts are unaffected (§18.1 P8.1).
    enabled = True
    #: **Zero is healthy.** The emitted count is the number of *actionable
    #: unmatched* elements, and the steady state everyone should want is that
    #: Grants.gov already carries them all. Source health is asserted on the
    #: parsed **inventory** instead -- see `check_health`, whose failure raises and
    #: therefore retains the last-known-good snapshot (§18.1 P8.5 case 6).
    min_records = 0
    #: Above the measured element count (63) so it can never bind on a healthy
    #: cycle, but bounded so a runaway parse cannot flood the catalog.
    max_records = 120
    #: A parser or reconciliation failure must not delete NASA records.
    retain_on_failure = True

    # §7.4 canary floors, derived from the measured source rather than guessed.
    EXPECTED_DIVISIONS = ("A", "B", "C", "D", "E", "F")
    MEASURED_ELEMENT_COUNT = 63     # 2026-08-17, ROSES-2025 Amendment 69
    MIN_ELEMENTS = 40               # see check_health for the derivation
    MAX_CROSS_TABLE_DELTA = 5

    def set_context(self, context: dict) -> None:
        """Take the catalog this run reconciles against (§18.1 P8.1).

        Without it `parse()` emits nothing, because "unmatched" is undecidable.
        """
        super().set_context(context)

    def _context_records(self) -> list:
        return list((self.context or {}).get("catalog_records") or [])

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
        table3_url = getattr(self._client, "last_url", None) or discovered["table3"]
        table2 = None
        if discovered["table2"]:
            try:
                table2 = self._client.get_text(discovered["table2"])
            except Exception:               # noqa: BLE001 - health, not fatal
                table2 = None
        return {
            "year": discovered["year"],
            "table3_url": table3_url,
            "table3_html": table3,
            "table2_html": table2,
            "amendment": self._amendment_of(table3_url),
        }

    @staticmethod
    def _amendment_of(resolved_url: str):
        match = _AMEND_RE.search(unquote(resolved_url or ""))
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

    # --- P8 reconciliation and emission ---------------------------------
    def reconcile(self, rows, *, catalog_records, year, today=None) -> dict:
        """Decide, for every program element, what this refresh should do with it.

        Pure and deterministic: same inventory plus same catalog gives the same
        answer. Returns counts and the element lists behind them, which become the
        source diagnostics and the product-gain measurement (§18.1 P8).
        """
        today = today or _dt.date.today()
        _overview, elements = self.split_rows(rows)
        index = catalog_roses_index(catalog_records)
        cycle = cycle_of(year)

        # A code that occurs twice in one cycle cannot be used as a *cross-source*
        # key for either occurrence -- measured: `D.3C` does exactly this, and it is
        # the only such code in the live source. It does **not** make the two rows
        # one element: they carry different titles, sit at different appendix
        # positions, offer different submission routes ("Phase-1 via ARK RPS" vs
        # "via NSPIRES"), and appear independently in Table 2 as well as Table 3.
        # Native identity is `(cycle, code, title)`, which separates them cleanly,
        # so a duplicate code alone must never make either row unpublishable.
        seen_codes: dict = {}
        for element in elements:
            seen_codes.setdefault(element["appendix_code"].upper(), 0)
            seen_codes[element["appendix_code"].upper()] += 1
        ambiguous_codes = sorted(
            code for code, count in seen_codes.items() if count > 1
        )

        matched, unmatched, actionable, inactive, review = [], [], [], [], []
        for element in elements:
            code = element["appendix_code"].upper()
            currentness = derive_currentness(element, today)
            element = dict(element, derived_currentness=currentness)
            catalog_ids = index["by_code"].get((cycle, code))
            duplicated_in_source = code in ambiguous_codes

            if catalog_ids and duplicated_in_source:
                # **The only genuinely ambiguous case.** A catalog record parses to
                # a code that names two native elements, so the code cannot say
                # which one it is. Fail closed: neither is emitted, and the reason
                # is recorded rather than being silently filed as "matched".
                element["matched_catalog_ids"] = catalog_ids
                element["review_reason"] = "ambiguous_code_matches_catalog_record"
                review.append(element)
                continue
            if catalog_ids:
                element["matched_catalog_ids"] = catalog_ids
                matched.append(element)
                continue

            # No catalog record carries this code, so nothing is ambiguous even if
            # the code is duplicated in the source: the two rows are two distinct
            # unmatched elements and each is judged on its own currentness.
            unmatched.append(element)
            if currentness == DERIVED_OPEN:
                actionable.append(element)
            else:
                inactive.append(element)

        return {
            "elements": len(elements),
            "matched": matched,
            "unmatched": unmatched,
            "actionable_unmatched": actionable,
            "inactive_unmatched": inactive,
            "review": review,
            # Informational: codes the source repeats. Reported even when they
            # suppress nothing, because it is a fact about the source.
            "ambiguous_source_codes": ambiguous_codes,
            "unresolved_catalog_records": index["unresolved"],
            "catalog_roses_records": sum(
                len(ids) for ids in index["by_code"].values()
            ),
            "cycle": cycle,
            "as_of": today.isoformat(),
        }

    def opportunity_for(self, element, year) -> CanonicalOpportunity:
        """One actionable unmatched element as a catalog opportunity.

        Every field comes from NASA's own table. Nothing is inferred, and the
        title follows the convention the catalog already uses for ROSES records
        (`ROSES25: A.14 Atmosphere`) so a later Grants.gov arrival collides on the
        framework's normalised-title test as well as on the code (§18.1 P8.3).
        """
        dates = [d for cell in element["due_date_cells"] for d in parse_dates(cell)]
        close_date = max(dates) if dates else None
        return CanonicalOpportunity(
            title=(
                f"ROSES{cycle_of(year)}: {element['appendix_code']} "
                f"{element['title']}"
            ),
            external_id=element_external_id(element, year),
            # Published only for the rows that carry it; never synthesised.
            opportunity_number=element_solicitation_number(element),
            url=element["element_url"],
            agency="NASA Headquarters",
            status="posted",
            close_date=close_date,
            # NASA's own wording, qualifiers intact: "(Step-1)", "(Mandatory NOI)",
            # "(Phase-1 via ARK RPS)", "No Due Date [3]".
            deadline_note=element["native_deadline_text"] or None,
            description=(
                f"NASA ROSES-{year} program element {element['appendix_code']}, "
                f"appendix division {element['division']}. Published status: "
                f"{element['native_status']}; due dates as printed: "
                f"{element['native_deadline_text'] or 'none'}. "
                "Source: ROSES Table 3 (SOLICITED RESEARCH PROGRAMS)."
            ),
        )

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        """Emit **actionable unmatched** elements only. DEC-13, in code.

        Order of operations matters and is the point of the method:

        1. health first, so missing rows can never be read as removals;
        2. reconcile against the catalog handed in by the merge;
        3. refuse to emit anything if reconciliation is ambiguous;
        4. emit the actionable unmatched elements, in appendix order.

        Inactive elements never reach this list, so they cannot enter the public
        catalog; they stay visible as inventory in `self.diagnostics`.
        """
        rows = self.rows(payload)
        health = self.check_health(payload, rows)
        catalog_records = self._context_records()
        report = self.reconcile(
            rows,
            catalog_records=catalog_records,
            year=payload.get("year"),
            today=(self.context or {}).get("as_of"),
        )
        self.diagnostics = {
            "health": health,
            "year": payload.get("year"),
            "amendment": payload.get("amendment"),
            "elements": report["elements"],
            "overview_rows": len(self.split_rows(rows)[0]),
            "catalog_roses_records": report["catalog_roses_records"],
            "matched": len(report["matched"]),
            "unmatched": len(report["unmatched"]),
            "actionable_unmatched": len(report["actionable_unmatched"]),
            "inactive_unmatched": len(report["inactive_unmatched"]),
            "native_status_counts": _counts(
                element["native_status"] for element in report["unmatched"]
            ),
            "derived_currentness_counts": _counts(
                element["derived_currentness"] for element in report["unmatched"]
            ),
            # The inventory itself, so the 51 inactive elements are visible
            # without being publishable.
            "inactive_inventory": [
                {
                    "appendix_code": element["appendix_code"],
                    "title": element["title"],
                    "native_status": element["native_status"],
                    "derived_currentness": element["derived_currentness"],
                    "native_deadline_text": element["native_deadline_text"],
                }
                for element in report["inactive_unmatched"]
            ],
            "review": [
                {
                    "appendix_code": element["appendix_code"],
                    "title": element["title"],
                    "reason": element.get("review_reason"),
                }
                for element in report["review"]
            ],
            "ambiguous_source_codes": report["ambiguous_source_codes"],
            "unresolved_catalog_records": report["unresolved_catalog_records"],
            "context_supplied": bool(catalog_records),
        }

        if not health["healthy"]:
            raise RosesReconciliationError(
                "ROSES source health failed, so nothing is emitted and the last "
                f"known good snapshot is retained: {'; '.join(health['failures'])}"
            )
        if report["unresolved_catalog_records"]:
            raise RosesReconciliationError(
                "catalog holds ROSES-numbered records whose appendix code cannot "
                "be parsed, so non-duplication cannot be proven: "
                + ", ".join(
                    str(item["opportunity_number"])
                    for item in report["unresolved_catalog_records"][:5]
                )
            )
        if not catalog_records:
            # Fail closed: without the catalog, "unmatched" is undecidable.
            return []

        year = payload.get("year")
        return [
            self.opportunity_for(element, year)
            for element in report["actionable_unmatched"]
        ]

    # --- the two S1 outputs ---------------------------------------------
    def standalone_inventory(self, rows, *, catalog_matches=()) -> list[dict]:
        """Program elements with no catalog record. Measured, never emitted."""
        matched = set(catalog_matches)
        _overview, elements = self.split_rows(rows)
        return [e for e in elements if e["identity"] not in matched]

    def subtopic_children(
        self,
        rows,
        *,
        parent_matches,
        as_of=None,
        health=None,
        document=None,
        source_version=None,
    ):
        """§5.1 `native` child records for elements that DO have a parent.

        `parent_matches` maps an element identity to the catalog
        `opportunity_id` it belongs to. Nothing is invented: every field comes
        from NASA's table.
        """
        # A native rung earns high confidence only after the existing source
        # canaries pass. Missing health is not permission to guess.
        if health is None:
            health = self.check_health({"table2_html": None}, rows)
        if not health.get("healthy"):
            return []
        from scripts import subtopic_records

        _overview, elements = self.split_rows(rows)
        by_parent = {}
        for element in elements:
            parent = parent_matches.get(element["identity"])
            if not parent:
                continue
            parent_record = parent if isinstance(parent, dict) else {
                "opportunity_id": str(parent),
                "status": "posted",
            }
            by_parent.setdefault(str(parent_record["opportunity_id"]), (
                parent_record,
                [],
            ))[1].append({
                "code": element["appendix_code"],
                "title": element["title"],
                "ordinal": element["appendix_order"],
                "summary": (
                    f"NASA ROSES program element {element['appendix_code']}: "
                    f"{element['title']}."
                ),
                "text": " ".join(filter(None, (
                    element["title"],
                    element["native_deadline_text"],
                    f"ROSES division {element['division']}",
                ))),
                "native_status": element["native_status"],
                "native_deadline_text": element["native_deadline_text"],
                "division": element["division"],
                "amended": element["amended"],
                "child_source_url": element["element_url"],
            })
        built = []
        for parent_record, children in by_parent.values():
            built.extend(subtopic_records.build_structured_records(
                parent_record,
                children,
                document=document or {},
                as_of=as_of,
                provenance=subtopic_records.NATIVE,
                confidence="high",
                method=None,
                source_version=source_version,
            ))
        return built

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
