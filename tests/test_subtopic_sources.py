"""Multi-attachment segmentation tests (§6.6).

Every behaviour here was forced by a measurement in docs/CORPUS_CENSUS.md, not
by speculation: seven secondary attachments carry a topic list and all seven are
revisions of a document already segmented, and one primary yields 113
extractable lines from 55 pages while matching a family inside prose.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures.minipdf import build_pdf, heading, line  # noqa: E402

from scripts import subtopic_sources as sources  # noqa: E402
from scripts.extract_document_evidence import extract_containers  # noqa: E402


def body_for(subject):
    return (
        f"This element supports fundamental studies of {subject}, including "
        f"operando characterization and reactor design relevant to {subject}. "
        f"Awards support single investigators and small teams pursuing "
        f"{subject} at laboratory scale, with catalytic chemistry throughout."
    )


def notice(headings, intro="Program announcement overview."):
    pages = [[heading("Overview"), line(intro)]]
    for text in headings:
        pages.append([heading(text), line(body_for(text))])
    outline = [(text, index + 1, 0) for index, text in enumerate(headings)]
    return build_pdf(pages, outline=outline)


TOPICS = [
    "Topic Area 1 Electrocatalysis",
    "Topic Area 2 Membrane Separations",
    "Topic Area 3 Materials Discovery",
]
BLAND = build_pdf([
    [heading("I. OVERVIEW INFORMATION"), line(body_for("administration"))],
    [heading("II. BASIC INFORMATION"), line(body_for("submission"))],
])
PDF_DOC = {"content_type": "application/pdf", "name": "notice.pdf",
           "url": "https://example.gov/notice.pdf"}


def detail_with(names):
    def fetcher(_opportunity_id):
        return {"data": {"n": names}}
    return fetcher


def collector_for(names):
    def collector(data):
        return [
            {"download_url": f"https://example.gov/{name}",
             "file_name": name, "id": str(index)}
            for index, name in enumerate(data["n"])
        ]
    return collector


def downloader(blobs):
    calls = []

    def download(url, headers=None):
        calls.append(url)
        name = url.rsplit("/", 1)[-1]
        if name not in blobs:
            raise RuntimeError(f"no such attachment: {name}")
        return {"content": blobs[name], "content_type": "application/pdf",
                "url": url}
    download.calls = calls
    return download


def run(record, primary, names, blobs, **kwargs):
    return sources.best_segmentation(
        record or {"opportunity_id": "1001"},
        primary,
        PDF_DOC,
        extract_containers=extract_containers,
        download=downloader(blobs),
        detail_fetcher=detail_with(names),
        collector=collector_for(names),
        **kwargs,
    )


class PrimaryFirstTests(unittest.TestCase):
    def test_a_segmenting_primary_costs_no_extra_fetch(self):
        download = downloader({})
        result, document, diagnostics = sources.best_segmentation(
            {"opportunity_id": "1001"},
            notice(TOPICS),
            PDF_DOC,
            extract_containers=extract_containers,
            download=download,
            detail_fetcher=detail_with(["other.pdf"]),
            collector=collector_for(["other.pdf"]),
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(document, PDF_DOC)
        self.assertEqual(download.calls, [], "a high-confidence primary fetched more")
        self.assertEqual(diagnostics["attempts"][0]["source"], "primary")

    def test_a_bland_primary_falls_through_to_an_attachment(self):
        result, document, _diagnostics = run(
            None, BLAND, ["appendix.pdf"], {"appendix.pdf": notice(TOPICS)}
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(document["name"], "appendix.pdf")
        self.assertEqual(document["source_kind"], "secondary_attachment")


class DeduplicationTests(unittest.TestCase):
    def test_a_revision_with_identical_bytes_is_not_segmented_twice(self):
        # The census case: 363065 would otherwise contribute the same Topic
        # Area list four times from four revisions.
        same = notice(TOPICS)
        result, _document, diagnostics = run(
            None, same,
            ["Amd_000001.pdf", "Amd_000002.pdf"],
            {"Amd_000001.pdf": same, "Amd_000002.pdf": same},
        )
        self.assertEqual(len(result.subtopics), 3)
        outcomes = [a["outcome"] for a in diagnostics["attempts"]]
        # The primary segments at high confidence, so no attachment is fetched
        # at all -- which is the strongest possible form of not duplicating.
        self.assertEqual(outcomes[0], "outline")

    def test_duplicate_attachments_are_skipped_when_the_primary_is_bland(self):
        same = notice(TOPICS)
        result, _document, diagnostics = run(
            None, BLAND,
            ["a.pdf", "b.pdf"],
            {"a.pdf": same, "b.pdf": same},
        )
        self.assertEqual(len(result.subtopics), 3)
        outcomes = [a.get("outcome") for a in diagnostics["attempts"]]
        self.assertIn("duplicate_hash", outcomes)
        self.assertEqual(outcomes.count("outline"), 1)


class RankingTests(unittest.TestCase):
    def test_the_best_result_wins_not_the_first(self):
        # Two attachments segment; the later one is better. Attachment order
        # must not decide, because 332894's degraded primary would win on it.
        four = notice(TOPICS + ["Topic Area 4 Reactor Engineering"])
        result, document, _diagnostics = run(
            None, BLAND,
            ["small.pdf", "big.pdf"],
            {"small.pdf": notice(TOPICS), "big.pdf": four},
        )
        self.assertEqual(len(result.subtopics), 4)
        self.assertEqual(document["name"], "big.pdf")

    def test_a_secondary_won_result_is_capped_at_low_confidence(self):
        # Measured precision of secondary-won lists is 0 of 1: CDC 360339
        # segments its M&E indicator attachment, not its five Components. Too
        # little evidence to publish on, and §18.3 says which way to err.
        result, document, _diagnostics = run(
            None, BLAND, ["appendix.pdf"], {"appendix.pdf": notice(TOPICS)}
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(document["source_kind"], "secondary_attachment")
        self.assertEqual(result.confidence, "low", "a secondary result may publish")

    def test_a_primary_result_keeps_its_confidence(self):
        result, document, _diagnostics = run(
            None, notice(TOPICS), [], {}
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(document, PDF_DOC)

    def test_confidence_outranks_count(self):
        self.assertGreater(
            sources.CONFIDENCE_RANK["high"], sources.CONFIDENCE_RANK["medium"]
        )
        self.assertGreater(
            sources.CONFIDENCE_RANK["medium"], sources.CONFIDENCE_RANK["low"]
        )


class RobustnessTests(unittest.TestCase):
    def test_a_failed_attachment_fetch_is_not_fatal(self):
        result, _document, diagnostics = run(
            None, BLAND,
            ["missing.pdf", "good.pdf"],
            {"good.pdf": notice(TOPICS)},
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertIn(
            "fetch_failed", [a.get("outcome") for a in diagnostics["attempts"]]
        )

    def test_a_failing_detail_fetch_yields_no_sources(self):
        def broken(_opportunity_id):
            raise RuntimeError("api down")

        self.assertEqual(
            sources.attachment_sources(
                "1001", detail_fetcher=broken, collector=collector_for([])
            ),
            [],
        )

    def test_unreadable_attachment_bytes_never_raise(self):
        result, _document, _diagnostics = run(
            None, BLAND, ["junk.pdf"], {"junk.pdf": b"\x00\x01 not a pdf"}
        )
        self.assertEqual(result.subtopics, ())

    def test_proposal_furniture_is_never_fetched(self):
        skipped = [
            "Attachment_F_DARPA_Cost_Proposal_Spreadsheet.xlsx",
            "Attachment_I_Schedule_of_Milestones_and_Payments.xlsx",
            "Appendix 2 - Privacy Act Statement.pdf",
            "Security Program Questionnaire - Appendix 1.docx",
        ]
        found = sources.attachment_sources(
            "1001",
            detail_fetcher=detail_with(skipped),
            collector=collector_for(skipped),
        )
        self.assertEqual(found, [])

    def test_the_attachment_count_is_capped(self):
        many = [f"file{index}.pdf" for index in range(20)]
        found = sources.attachment_sources(
            "1001",
            detail_fetcher=detail_with(many),
            collector=collector_for(many),
        )
        self.assertEqual(len(found), sources.MAX_ATTACHMENTS)

    def test_an_exhausted_run_budget_stops_fetching(self):
        class Spent:
            def exhausted(self):
                return True

        download = downloader({"a.pdf": notice(TOPICS)})
        result, _document, diagnostics = sources.best_segmentation(
            {"opportunity_id": "1001"},
            BLAND,
            PDF_DOC,
            extract_containers=extract_containers,
            download=download,
            detail_fetcher=detail_with(["a.pdf"]),
            collector=collector_for(["a.pdf"]),
            run_budget=Spent(),
        )
        self.assertEqual(result.subtopics, ())
        self.assertEqual(download.calls, [])
        self.assertIn(
            "run_budget", [a.get("outcome") for a in diagnostics["attempts"]]
        )


if __name__ == "__main__":
    unittest.main()
