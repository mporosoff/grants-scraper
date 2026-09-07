"""Structure regressions; synthetic snippets never enter maintained inputs."""
import unittest
from unittest.mock import Mock, patch

from scripts import extract_document_evidence as evidence
from scripts.notice_structure import NoticeHTMLParser
from scripts.nsf_funding import parse_nsf_funding_page


class NoticeStructureTests(unittest.TestCase):
    def test_short_cells_retain_headers_empty_columns_and_locations(self):
        html = b'''<nav>Unrelated deadline: January 1, 2000</nav><h2 id="dates">Key Dates</h2>
        <table><tr><th>Stage</th><th>Required</th><th>Deadline</th></tr>
        <tr><td>LOI</td><td>Yes</td><td>October 20, 2026</td></tr>
        <tr><td>Application</td><td></td><td>TBD</td></tr></table>
        <h2>Funding</h2><table><tr><th>Award Ceiling</th><td>$560,000</td></tr></table>'''
        containers, diagnostics = evidence.extract_html_sections(html)
        rows = [block for container in containers for block in container["structure"] if block["kind"] == "table_row"]
        self.assertEqual([c["text"] for c in rows[1]["cells"]], ["LOI", "Yes", "October 20, 2026"])
        self.assertEqual([c["text"] for c in rows[2]["cells"]], ["Application", "", "TBD"])
        self.assertEqual(rows[2]["cells"][2]["column"], 2)
        self.assertEqual(rows[1]["header_rows"][0][2]["text"], "Deadline")
        self.assertEqual(rows[1]["heading_path"], ["Key Dates"])
        self.assertIn("$560,000", " ".join(c["text"] for c in containers))
        self.assertNotIn("January", " ".join(c["text"] for c in containers))
        self.assertFalse(diagnostics["truncated"])
        self.assertEqual(diagnostics["warnings"], [])
        for container in containers:
            for block in container["structure"]:
                self.assertEqual(container["text"][slice(*block["span"])], block["text"])

    def test_native_nih_field_identity_survives_sibling_label_and_value(self):
        parser = NoticeHTMLParser()
        parser.feed('''<h2>Key Dates</h2><div class="datalabel" data-element-id="date-field">Application Due Date(s)</div>
        <div data-element-id="date-field" data-section-code="KD"><p>October 20, 2026</p><p>October 19, 2027</p></div>''')
        parser.close()
        for block in parser.blocks[1:]:
            self.assertTrue(any(a.get("data-element-id") == "date-field" for a in block["ancestors"]))
        self.assertEqual(parser.blocks[-1]["text"], "October 19, 2027")

    def test_optional_cell_end_tags_and_nested_tables_preserve_boundaries(self):
        parser = NoticeHTMLParser()
        parser.feed('<table><tr><th>Stage<th>Date<tr><td>LOI<td>TBD<tr><td>Application<td>May 1, 2027</table>')
        parser.close()
        self.assertEqual([[c["text"] for c in row["cells"]] for row in parser.blocks],
                         [["Stage", "Date"], ["LOI", "TBD"], ["Application", "May 1, 2027"]])
        self.assertEqual(parser.diagnostics, [])
        parser = NoticeHTMLParser()
        parser.feed('<table><tr><td>Outer<table><tr><td>Inner</td></tr></table></td><td>Yes</td></tr></table>')
        parser.close()
        self.assertEqual(len(parser.blocks), 1)
        self.assertEqual(len(parser.blocks[0]["cells"]), 2)
        self.assertTrue(parser.blocks[0]["cells"][0]["nested_table"])
        self.assertEqual(parser.blocks[0]["cells"][1]["text"], "Yes")
        self.assertEqual(parser.diagnostics, ["nested_table_structure"])

    def test_linked_navigation_is_removed_without_dropping_short_substantive_fields(self):
        parser = NoticeHTMLParser()
        parser.feed('<div class="table-of-contents"><a href="#rules">Eligibility</a></div><h2>Eligibility</h2><p>Yes</p><p>No</p>')
        parser.close()
        self.assertEqual([b["text"] for b in parser.blocks], ["Eligibility", "Yes", "No"])

    def test_nsf_void_elements_and_sidebar_do_not_change_program_ownership(self):
        body = "Research in quantum photonic devices and integrated electronic systems. " * 3
        for void in ['<br>', '<br/>', '<img src="x">', '<input type="hidden">']:
            with self.subTest(void=void):
                page = parse_nsf_funding_page(f'<main><div class="field-funding-synopsis"><p>{body}{void}Additional scope.</p></div>'
                    '<aside>Status: Archived. Replaced by NSF 25-999. Aquatic ecology.</aside><p>Status: Current</p></main>')
                self.assertEqual(page["status"], "current")
                self.assertNotIn("Aquatic", page["text"])
                self.assertIsNone(page["replacement_opportunity_number"])
        archived = parse_nsf_funding_page(f'<nav>Status: Current</nav><main><h1>Status: Archived</h1>'
            f'<div class="field-funding-synopsis">{body}</div><p>Replaced by NSF 26-999</p></main>')
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(archived["replacement_opportunity_number"], "NSF-26-999")

    def test_pdf_character_truncation_and_unreadable_pages_are_reported(self):
        pages = [Mock(extract_text=Mock(return_value="A substantive section\n" + "X" * 100)),
                 Mock(extract_text=Mock(side_effect=ValueError("unreadable fixture")))]
        with patch.object(evidence, "PdfReader", return_value=Mock(is_encrypted=False, pages=pages)), patch.object(evidence, "MAX_PAGE_CHARS", 40):
            containers, diagnostics = evidence.extract_pdf_pages(b"fixture")
        self.assertTrue(diagnostics["truncated"])
        self.assertEqual(diagnostics["truncated_pages"], [1])
        self.assertEqual(diagnostics["unreadable_pages"], [2])
        self.assertEqual(containers[0]["structure"][0]["page"], 1)
        self.assertLessEqual(len(containers[0]["text"]), 40)

    def test_encrypted_unreadable_pdf_is_not_a_successful_empty_document(self):
        with patch.object(evidence, "PdfReader", return_value=Mock(is_encrypted=True, decrypt=Mock(return_value=0))):
            with self.assertRaisesRegex(RuntimeError, "encrypted"):
                evidence.extract_pdf_pages(b"fixture")

    def test_actual_content_signature_precedes_stale_attachment_name(self):
        # FDA's canonical attachment name may end in .pdf while the selected
        # official source is the HTML NOFO. Do not force HTML through pypdf.
        content = b'<!doctype html><html><h2>Application deadline</h2><p>May 1, 2027</p></html>'
        containers, diagnostics = evidence.extract_containers(content, 'text/html', 'old-attachment.pdf', 'https://example.gov/notice.html')
        self.assertEqual(diagnostics['content_kind'], 'html')
        self.assertIn('May 1, 2027', containers[0]['text'])
        self.assertEqual(evidence.content_kind(b'%PDF-1.7', 'text/html', 'notice.html', 'https://example.gov/notice'), 'pdf')

    def test_pdf_layout_keeps_column_positions_without_inventing_headers(self):
        raw = "Stage       Required       Deadline\nLOI         Yes            October 20, 2026\nApplication                TBD"
        page = Mock(extract_text=Mock(return_value=raw))
        with patch.object(evidence, "PdfReader", return_value=Mock(is_encrypted=False, pages=[page])):
            containers, diagnostics = evidence.extract_pdf_pages(b"fixture")
        rows = containers[0]["layout_rows"]
        self.assertEqual([c["text"] for c in rows[1]["cells"]], ["LOI", "Yes", "October 20, 2026"])
        self.assertEqual(rows[2]["cells"][1]["column_start"], rows[1]["cells"][2]["column_start"])
        self.assertNotIn("required", rows[2])
        self.assertEqual(diagnostics["layout_unavailable_pages"], [])

    def test_citation_identifies_owned_block_without_publishing_full_structure(self):
        containers, _ = evidence.extract_html_sections(b'<h2>Funding</h2><p>Award Ceiling: $560,000</p>')
        container = containers[0]
        start = container["text"].index("$560")
        citation = evidence.citation_for(container, {"url": "https://example.org/notice", "sha256": "fixture"}, start, start + 8, "fixed-time")
        self.assertEqual(citation["structural_reference"]["kind"], "paragraph")
        self.assertNotIn("structure", citation)
        fact = evidence.make_fact("fixture", "award_range", "Per-award ceiling", 560000, "$560,000", citation)
        self.assertEqual(fact["source_authority"], "machine_extracted_official_document")
        self.assertEqual(fact["confidence"], "machine_extracted_needs_verification")

    def test_exchange_named_anchor_owns_one_complete_group(self):
        identifier = "00000000-0000-0000-0000-000000000001"
        url = "https://eere-exchange.energy.gov/#FoaId" + identifier
        owned = f'<div class="foaGroup"><h2><a name="FoaId{identifier}">Official notice</a></h2><div>Concept paper due October 9, 2026</div></div>'
        sibling = '<div class="foaGroup"><h2>Different notice</h2><div>Application due January 1, 2000</div></div>'
        result = evidence.scoped_html((sibling + owned + sibling).encode(), url)
        self.assertEqual(result.decode(), owned)
        self.assertEqual(evidence.scoped_html(result, url), result)
        for malformed in [owned + owned, owned.removesuffix('</div>'), sibling]:
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                evidence.scoped_html(malformed.encode(), url)


if __name__ == "__main__":
    unittest.main()
