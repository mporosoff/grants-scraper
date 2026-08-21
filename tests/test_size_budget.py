"""Absolute size budgets for the published catalog and the subtopic cache.

The budget is deliberately **absolute**, not a multiplier over the current
size. A 1.5x multiplier would set a ~37 MB ceiling on a 24 MB file, which is
not a budget -- it is permission to nearly double. See
docs/TOPIC_LAYER_PLAN.md §12 and §18.1 item A4.

`data/opportunities.js` is what every visitor downloads before the page is
usable, so the ceiling protects page-load time, not disk. GitHub warns on
files above 50 MB, so 32 MiB also leaves headroom for ordinary catalog growth
on top of anything the subtopic layer adds.

The per-subtopic cap governs the display payload: at 2 KiB serialized, 1,000
subtopics cost about 2 MB. Retrieval terms are budgeted once in the sidecar's
inverted index and must not be duplicated on every display record.
"""

from pathlib import Path
import json
import unittest
import warnings


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

MIB = 1024 * 1024

# Hard ceiling. Above this the build fails.
CATALOG_HARD_LIMIT_BYTES = 32 * MIB
# Advisory. Above this the build still passes but says so, because the gap
# between warn and fail is the only room left to react in.
CATALOG_WARN_LIMIT_BYTES = 28 * MIB
# Per display record: 600-char summary + (in P10) up to 60 term_display entries
# that are trimmed to the remaining room + scalars. The 400-term retrieval map
# lives only in search_index.
SUBTOPIC_RECORD_LIMIT_BYTES = 2 * 1024

# §12 budgets what a card can render, not maintenance-only provenance and
# change-detection diagnostics stored beside it. Keep this projection explicit
# so a new user-facing field cannot enter the card budget invisibly.
SUBTOPIC_DISPLAY_FIELDS = frozenset({
    "record_type",
    "child_type",
    "subtopic_id",
    "opportunity_id",
    "parent_id",
    "parent_opportunity_number",
    "subtopic_code",
    "subtopic_ordinal",
    "title",
    "summary",
    "term_display",
    "subtopic_source",
    "status",
    "topic_areas",
    "program_area_labels",
    "page_start",
    "page_end",
    "evidence_anchor",
    "source_document_url",
    "confidence",
    "own_deadline",
    "own_deadline_is_advisory",
    "group_id",
    "parent_subtopic_id",
    "publication_state",
    "publication_reason",
})

CATALOG = REPOSITORY_ROOT / "data" / "opportunities.js"
SUBTOPIC_RECORDS = REPOSITORY_ROOT / "data" / "subtopics.js"


def _megabytes(value):
    return f"{value / MIB:.2f} MiB"


class CatalogSizeBudgetTests(unittest.TestCase):
    def test_catalog_stays_under_the_hard_ceiling(self):
        if not CATALOG.exists():
            self.skipTest(f"{CATALOG} has not been built in this checkout")

        size = CATALOG.stat().st_size

        self.assertLessEqual(
            size,
            CATALOG_HARD_LIMIT_BYTES,
            f"data/opportunities.js is {_megabytes(size)}, over the "
            f"{_megabytes(CATALOG_HARD_LIMIT_BYTES)} hard ceiling. Every "
            "visitor downloads this file before the page is usable. Cut "
            "per-record cost -- do not raise this limit (§12).",
        )

    def test_catalog_warns_before_it_reaches_the_ceiling(self):
        if not CATALOG.exists():
            self.skipTest(f"{CATALOG} has not been built in this checkout")

        size = CATALOG.stat().st_size

        if size > CATALOG_WARN_LIMIT_BYTES:
            warnings.warn(
                f"data/opportunities.js is {_megabytes(size)}, past the "
                f"{_megabytes(CATALOG_WARN_LIMIT_BYTES)} warning threshold "
                f"and approaching the {_megabytes(CATALOG_HARD_LIMIT_BYTES)} "
                "hard ceiling (§12).",
                ResourceWarning,
                stacklevel=2,
            )

        # The warning is the signal; the assertion keeps the headroom visible
        # in the failure message once the ceiling is genuinely at risk.
        self.assertLessEqual(size, CATALOG_HARD_LIMIT_BYTES)


class SubtopicRecordSizeBudgetTests(unittest.TestCase):
    def test_each_subtopic_record_stays_within_its_serialized_budget(self):
        if not SUBTOPIC_RECORDS.exists():
            self.skipTest(
                "data/subtopics.js does not exist yet; the cache "
                "arrives with package C"
            )

        text = SUBTOPIC_RECORDS.read_text(encoding="utf-8")
        payload = json.loads(
            text.split("globalThis.SUBTOPIC_CATALOG=", 1)[1].rstrip(";\n")
        )
        records = payload.get("records") or {}

        oversized = []
        for key, entry in records.items():
            for index, subtopic in enumerate(entry.get("subtopics") or []):
                display = {
                    field: subtopic[field]
                    for field in SUBTOPIC_DISPLAY_FIELDS
                    if field in subtopic
                }
                size = len(
                    json.dumps(
                        display, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                )
                if size > SUBTOPIC_RECORD_LIMIT_BYTES:
                    oversized.append((key, index, size))

        self.assertEqual(
            oversized,
            [],
            "Subtopic records over the "
            f"{SUBTOPIC_RECORD_LIMIT_BYTES}-byte serialized budget: "
            f"{oversized[:10]}. At 2 KiB, 1,000 subtopics cost about 2 MB, "
            "which is the display budget this feature has to live inside. "
            "Keep retrieval terms in the inverted index and trim redundant "
            "display fields rather than raising the ceiling (§12).",
        )


if __name__ == "__main__":
    unittest.main()
