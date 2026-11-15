from datetime import date
from io import BytesIO
import unittest

from scripts import enrich_catalog, extract_document_evidence, pull_grants, source_documents, subtopic_sources
from scripts.build_catalog import iter_catalog_records


CLOSURE_DATE = date(2026, 11, 13)
AGENCY_URL = 'https://agency.example.gov/dfop0019410'
ATTACHMENT_NAME = 'Annual Program Statement Closed.pdf'
ATTACHMENT_URL = 'https://grants.gov/grantsws/rest/opportunity/att/download/355655'
RECORD = {'opportunity_id': '363660', 'opportunity_number': 'DFOP0019410', 'agency_code': 'DOS-AF',
          'agency': 'Bureau of African Affairs', 'source': 'Grants.gov', 'status': 'posted',
          'close_date': '2027-05-31', 'last_updated': '2026-11-13'}
ATTACHMENT = {'id': 355655, 'fileName': ATTACHMENT_NAME, 'mimeType': 'application/pdf', 'fileLobSize': 83402}
DETAIL = {'opportunityNumber': 'DFOP0019410', 'owningAgencyCode': 'DOS-AF',
          'synopsis': {'fundingDescLinkUrl': AGENCY_URL},
          'synopsisAttachmentFolders': [{'folderType': 'Full Announcement', 'synopsisAttachments': [ATTACHMENT]}]}


def xml_record(record):
    return f"""<OpportunitySynopsisDetail_1_0>
        <OpportunityID>{record['opportunity_id']}</OpportunityID>
        <OpportunityNumber>{record['opportunity_number']}</OpportunityNumber>
        <AgencyCode>{record['agency_code']}</AgencyCode>
        <OpportunityTitle>U.S.-Africa Strategic Investment Program</OpportunityTitle>
        <PostDate>08192026</PostDate>
        <CloseDate>05312027</CloseDate>
        </OpportunitySynopsisDetail_1_0>"""


class GrantsClosureNoticeTests(unittest.TestCase):
    def test_xml_withholds_only_the_verified_issuance_after_the_closure(self):
        other_records = [dict(RECORD, **{field: value}) for field, value in (
            ('opportunity_id', '365000'), ('opportunity_number', 'DFOPNEW'), ('agency_code', 'DOS-OTHER'))]
        xml = '<Grants>' + ''.join(xml_record(r) for r in [RECORD, *other_records]) + '</Grants>'
        before = list(iter_catalog_records(BytesIO(xml.encode()), date(2026, 11, 12)))
        after = list(iter_catalog_records(BytesIO(xml.encode()), CLOSURE_DATE))
        key = lambda row: (row['opportunity_id'], row['opportunity_number'], row['agency_code'])
        self.assertEqual(list(map(key, before)), list(map(key, [RECORD, *other_records])))
        self.assertEqual(list(map(key, after)), list(map(key, other_records)))

    def test_api_withdrawal_cannot_shadow_a_distinct_reissue(self):
        reissue = dict(RECORD, opportunity_id='365000', last_updated='2026-10-15', version=1)
        self.assertEqual(pull_grants.record_identity(RECORD), pull_grants.record_identity(reissue))
        result, counts = pull_grants.prepare_records([dict(RECORD, version=2), reissue], CLOSURE_DATE)
        self.assertEqual(result, [reissue])
        self.assertEqual(counts['closed_removed_count'], 1)
        self.assertEqual(counts['deduplicated_count'], 0)

    def test_attachment_selection_cannot_recover_closure_from_a_duplicate_route(self):
        urls = [ATTACHMENT_URL, 'https://agency.example.gov/Annual%20Program%20Statement%20Closed.pdf']
        attachments = pull_grants.collect_attachments(DETAIL)
        self.assertEqual(attachments[0]['download_url'], ATTACHMENT_URL)
        self.assertIsNone(enrich_catalog.select_primary_document(attachments, urls))
        detail = dict(DETAIL, synopsisDocumentURLs=urls)
        normalized = pull_grants.normalize({'id': '363660', 'oppStatus': 'posted'}, detail)
        self.assertIsNone(normalized['nofo_pdf_url'])
        self.assertEqual(normalized['primary_document_url'], AGENCY_URL)
        packed = enrich_catalog.compact_detail(RECORD, detail, enrich_catalog.utc_now())
        self.assertIsNone(packed['primary_document'])
        self.assertEqual(packed['document_urls'], [])
        self.assertEqual(packed['attachment_count'], 1)
        self.assertEqual(subtopic_sources.attachment_sources(
            '363660', detail_fetcher=lambda _: detail, collector=pull_grants.collect_attachments), [])

    def test_real_announcements_that_mention_closure_are_still_eligible(self):
        attachment = pull_grants.collect_attachments(DETAIL)[0]
        for name in ('Annual Program Statement V4.pdf', 'Annual Program Statement Closed and Reopened.pdf',
                     'Funding Opportunity Announcement for Closed-Loop Systems.pdf'):
            with self.subTest(name=name):
                control = dict(attachment, file_name=name, description='Full Announcement')
                self.assertFalse(source_documents.is_closure_notice_document(control))
                self.assertEqual(enrich_catalog.select_primary_document([control])['name'], name)

    def test_old_cached_closure_cannot_override_the_agency_route_or_republish_facts(self):
        record = dict(RECORD, funding_opportunity_url=AGENCY_URL, primary_document_url=ATTACHMENT_URL,
                      primary_document_name=ATTACHMENT_NAME, primary_document_source='Grants.gov attachment',
                      primary_document_confidence='medium', document_urls=[ATTACHMENT_URL])
        self.assertEqual(source_documents.document_candidates(record)[0]['url'], AGENCY_URL)
        self.assertEqual(len(source_documents.document_candidates(record)), 1)
        self.assertEqual(extract_document_evidence.source_for_record(record)['url'], AGENCY_URL)
        cache = {'primary_document': {'url': ATTACHMENT_URL, 'name': ATTACHMENT_NAME},
                 'document_urls': [ATTACHMENT_URL]}
        merged = enrich_catalog.merge_detail(record, cache, CLOSURE_DATE)
        self.assertIsNone(merged.get('primary_document_url'))
        self.assertEqual(merged['funding_opportunity_url'], AGENCY_URL)
        self.assertEqual(merged['document_urls'], [])
        retrieved = {'url': ATTACHMENT_URL, 'name': ATTACHMENT_NAME, 'sha256': 'a' * 64}
        entry = {'document': retrieved, 'status': 'current', 'facts': [{'id': 'unsupported'}],
                 'program_areas': [{'label': 'Unsupported'}], 'subtopics': [{'title': 'Unsupported'}]}
        projected = extract_document_evidence.merge_document_entry(merged, entry)
        self.assertIsNone(projected['document_evidence'])
        self.assertEqual(projected['close_date'], RECORD['close_date'])
        self.assertEqual(entry['facts'], [])
        self.assertEqual(entry['subtopics'], [])
        self.assertEqual(entry['primary_document_guard']['reason'], 'closure_notice')
        self.assertEqual(entry['document'], retrieved)

    def test_an_unenriched_legacy_row_drops_the_withheld_url_but_keeps_the_grants_listing(self):
        detail_page = 'https://www.grants.gov/search-results-detail/363660'
        row = dict(RECORD, primary_document_url=ATTACHMENT_URL, primary_document_name=ATTACHMENT_NAME,
                   funding_opportunity_url=ATTACHMENT_URL, detail_page=detail_page,
                   document_urls=[ATTACHMENT_URL, AGENCY_URL])
        merged = enrich_catalog.merge_detail(row, None, CLOSURE_DATE)
        self.assertIsNone(merged.get('primary_document_url'))
        self.assertIsNone(merged['funding_opportunity_url'])
        self.assertEqual(merged['detail_page'], detail_page)
        self.assertEqual(merged['document_urls'], [AGENCY_URL])
