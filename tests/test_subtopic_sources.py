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


def html_notice(headings):
    """An announcement delivered as HTML, the shape NIH posts 111 times.

    Deliberately larger than MIN_HTML_BYTES: the real ones average ~145 KB, and
    a fixture under the stub threshold is filtered before it is ever fetched --
    which is how the first draft of this test failed.
    """
    prose = (
        "Awards support single investigators and small teams working at "
        "laboratory scale, with operando characterization and reactor design "
        "throughout the period of performance. Applications are reviewed for "
        "scientific merit and for the qualifications of the research team. "
    ) * 3
    body = [b"<!doctype html><html><body><h1>Funding opportunity</h1>"]
    for text in headings:
        # The code appears in the heading and NOWHERE in the prose, which is
        # what makes this a test of the section tree rather than of the
        # ordinary text-scanning layers.
        body.append(f"<h2>{text}</h2><p>{prose}</p>".encode())
    body.append(b"</body></html>")
    return b"".join(body)


class HtmlAttachmentTests(unittest.TestCase):
    """§18.1 Cov2 -- 366 .html attachments, all NIH, 255 of them stubs."""

    def test_a_sub_kilobyte_stub_is_never_offered(self):
        def collector(data):
            return [
                {"download_url": "https://example.gov/PAR-25-210.html",
                 "file_name": "PAR-25-210-Full-Announcement.html",
                 "size_bytes": 422, "id": "1"},
            ]

        self.assertEqual(
            sources.attachment_sources(
                "1001", detail_fetcher=detail_with([]), collector=collector
            ),
            [],
        )

    def test_a_full_html_announcement_is_offered_and_carries_its_size(self):
        def collector(data):
            return [
                {"download_url": "https://example.gov/RFA-RM-27-002.html",
                 "file_name": "RFA-RM-27-002-Full-Announcement.html",
                 "size_bytes": 137_389, "id": "1"},
            ]

        found = sources.attachment_sources(
            "1001", detail_fetcher=detail_with([]), collector=collector
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["size"], 137_389)

    def test_html_bytes_reach_the_container_path_but_headings_are_not_an_outline(self):
        """Cov2 selects and parses HTML. It does **not** yet segment it.

        This test asserts a measured gap, not a desired behaviour, and it was
        rewritten during the Cov2 commit when it failed: extract_html_sections
        puts the heading in the container's ``section`` and the prose in its
        ``text``, so every text-scanning family looks straight past the
        headings. §6.6 says to "use the section tree as the outline equivalent"
        and nothing does.

        Not built here, deliberately. Cov2's own measurement is that **0 of 20
        non-stub NIH HTML announcements contain a fundable list** -- so an HTML
        outline layer would be speculative work against a population measured
        to yield nothing. When something does need it, this test is the
        record of what is missing; flip it and build the layer then.
        """
        page = html_notice(TOPICS)

        def collector(data):
            return [
                {"download_url": "https://example.gov/notice.html",
                 "file_name": "notice.html", "size_bytes": len(page), "id": "1"},
            ]

        fetched = []

        def download(url, headers=None):
            fetched.append(url)
            return {"content": page, "content_type": "text/html", "url": url}

        containers, extraction = extract_containers(
            page, "text/html", "notice.html", "https://example.gov/notice.html"
        )
        self.assertEqual(extraction["content_kind"], "html")
        self.assertEqual(len(containers), len(TOPICS))
        self.assertIn(
            TOPICS[0], [container.get("section") for container in containers],
            "the h2 headings did not survive into the section tree",
        )
        self.assertTrue(
            all(container.get("page") is None for container in containers)
        )

        result, _document, _diagnostics = sources.segment_without_primary(
            {"opportunity_id": "1001"},
            extract_containers=extract_containers,
            download=download,
            detail_fetcher=detail_with([]),
            collector=collector,
        )
        self.assertEqual(
            fetched, ["https://example.gov/notice.html"],
            "the HTML attachment was not selected for a fetch",
        )
        self.assertEqual(
            result.subtopics, (),
            "HTML headings now segment -- delete this test and assert the list",
        )

    def test_the_stub_rule_touches_only_html(self):
        self.assertFalse(sources._is_html_stub("tiny.pdf", 400))
        self.assertFalse(sources._is_html_stub("notice.html", None))
        self.assertTrue(sources._is_html_stub("notice.HTML", 400))


class SubtopicOnlySourceTests(unittest.TestCase):
    """§18.1 Cov1 -- records source_for_record() declines.

    Measured: it declines 685 of 1,475 records, 236 of which carry live
    attachments and 221 an agency URL declined only for needing no gap-fill
    (docs/COVERAGE_SURVEY.md stage 3).
    """

    def test_an_attachment_is_segmented_with_no_primary_at_all(self):
        result, document, _diagnostics = sources.segment_without_primary(
            {"opportunity_id": "1001"},
            extract_containers=extract_containers,
            download=downloader({"appendix.pdf": notice(TOPICS)}),
            detail_fetcher=detail_with(["appendix.pdf"]),
            collector=collector_for(["appendix.pdf"]),
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(document["name"], "appendix.pdf")

    def test_no_attachments_and_no_primary_yields_nothing_and_never_raises(self):
        result, document, _diagnostics = sources.segment_without_primary(
            {"opportunity_id": "1001"},
            extract_containers=extract_containers,
            download=downloader({}),
            detail_fetcher=detail_with([]),
            collector=collector_for([]),
        )
        self.assertEqual(result.subtopics, ())
        self.assertIsNone(document)

    def test_the_agency_url_is_offered_only_when_the_record_carries_one(self):
        self.assertIsNone(sources.subtopic_only_primary({}))
        self.assertIsNone(
            sources.subtopic_only_primary({"funding_opportunity_url": None})
        )
        source = sources.subtopic_only_primary(
            {"funding_opportunity_url": "https://agency.example/program"}
        )
        self.assertEqual(source["url"], "https://agency.example/program")
        self.assertEqual(source["kind"], "subtopic_agency_notice")


if __name__ == "__main__":
    unittest.main()
