"""Transport representations must stay bound to the catalog's exact public notice."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import unittest
from unittest.mock import patch

from scripts import document_acquisition as acquisition
from scripts import extract_document_evidence as evidence


IDENTIFIER = 'a' * 32
URL = 'https://sam.gov/opp/' + IDENTIFIER + '/view'
CONTENT = b'<html><body><h1>Research solicitation</h1><p>Applications are due December 14, 2026.</p></body></html>'


def inputs():
    record = {'opportunity_id': 'sam-gov:' + IDENTIFIER, 'opportunity_number': 'EXAMPLE-26-01',
              'title': 'Research solicitation', 'source': 'SAM.gov', 'status': 'posted',
              'sam_review_sha256': 'b' * 64, 'sam_organization_id': '100001'}
    source = {'url': URL, 'name': None, 'kind': 'agency_notice'}
    provenance = {'schema_version': 1, 'policy': acquisition.SAM_POLICY,
                  'representation': 'owned-description-html', 'notice_id': IDENTIFIER,
                  'api_url': 'https://sam.gov/api/prod/opps/v2/opportunities/' + IDENTIFIER,
                  'body_sha256': hashlib.sha256(CONTENT).hexdigest(), 'review_sha256': 'b' * 64,
                  'organization_id': '100001', 'solicitation_number': 'EXAMPLE-26-01'}
    response = {'status_code': 200, 'content': CONTENT, 'url': URL,
                'content_type': 'text/html', 'retrieval_provenance': provenance}
    return record, source, response


class AcquisitionIntegrationContracts(unittest.TestCase):
    def test_sam_download_uses_the_exact_public_reader_without_generic_fallback(self):
        _, _, response = inputs()
        with patch.object(evidence, 'validate_public_url') as validate, \
                patch.object(acquisition, 'read_document', return_value=response) as read, \
                patch.object(evidence.requests, 'Session') as session:
            self.assertEqual(evidence.download_document(URL, maximum_bytes=4096), response)
        validate.assert_called_once_with(URL)
        read.assert_called_once_with(URL, None, timeout=30, maximum_bytes=4096)
        session.assert_not_called()

    def test_failed_claimed_sam_route_never_falls_back_to_the_spa_shell(self):
        with patch.object(evidence, 'validate_public_url'), \
                patch.object(acquisition, 'read_document', side_effect=acquisition.DocumentAcquisitionError('sam_notice_unavailable')), \
                patch.object(evidence.requests, 'Session') as session:
            with self.assertRaises(acquisition.DocumentAcquisitionError):
                evidence.download_document(URL)
        session.assert_not_called()

    def test_exact_public_representation_is_retained_and_same_bytes_replay_keeps_provenance(self):
        record, source, response = inputs()
        original = deepcopy(response)
        stamp = datetime(2026, 10, 16, tzinfo=timezone.utc)
        entry, _ = evidence.build_document_entry(record, source, response, None, stamp)
        self.assertEqual(entry['document']['retrieval_provenance'], response['retrieval_provenance'])
        replay, extracted = evidence.build_document_entry(record, source, response, entry, stamp)
        self.assertFalse(extracted)
        self.assertEqual(replay['document']['retrieval_provenance'], response['retrieval_provenance'])
        self.assertEqual(response, original)

    def test_identity_review_body_and_metadata_conflicts_fail_before_fact_extraction(self):
        changes = [('notice_id', 'c' * 32), ('review_sha256', 'c' * 64),
                   ('organization_id', '200002'), ('solicitation_number', 'OTHER-26-01'),
                   ('api_url', 'https://other.example/notice'), ('body_sha256', 'c' * 64),
                   ('policy', 'unverified'), ('schema_version', True), ('contacts', 'private')]
        for key, value in changes:
            record, source, response = inputs()
            response['retrieval_provenance'][key] = value
            before = deepcopy(response)
            with self.subTest(key=key), patch.object(evidence, 'extract_document_facts') as extract:
                with self.assertRaises(acquisition.DocumentAcquisitionError):
                    evidence.build_document_entry(record, source, response, None,
                                                  datetime(2026, 10, 16, tzinfo=timezone.utc))
                extract.assert_not_called()
            self.assertEqual(response, before)

    def test_sam_representation_cannot_be_applied_to_another_source_or_response_route(self):
        for field in ('source', 'response'):
            record, source, response = inputs()
            (source if field == 'source' else response)['url'] = 'https://agency.example/notice'
            with self.subTest(field=field), self.assertRaises(acquisition.DocumentAcquisitionError):
                evidence.verified_retrieval_provenance(record, source, response)

    def test_verified_source_identity_is_independent_of_transport_profile(self):
        record, source, _ = inputs()
        expected = evidence.source_signature(record, source)
        with patch.object(acquisition, 'acquisition_identity', return_value='changed-transport'):
            self.assertEqual(evidence.source_signature(record, source), expected)


if __name__ == '__main__':
    unittest.main()
