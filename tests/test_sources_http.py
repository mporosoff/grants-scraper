"""Source request headers survive the shared safe downloader; no network calls."""

import unittest
from unittest.mock import patch

import requests

from scripts import extract_document_evidence as documents
from scripts.sources import http


class SourceRequestProfileTests(unittest.TestCase):
    def response(self):
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "text/html"
        response.encoding = "utf-8"
        response._content = b"official source"
        response._content_consumed = True
        return response

    def fetch(self, headers=None, *, document=False):
        client = http.PoliteClient(request_delay=0, timeout=(4, 8))
        with patch.object(documents, "validate_public_url"), patch.object(
            client._session, "send", return_value=self.response()
        ) as send:
            if document:
                documents.download_document("https://agency.example/notice", session=client._session)
            else:
                self.assertEqual(client.get_text("https://agency.example/notice", headers=headers), "official source")
                self.assertEqual(client.last_url, "https://agency.example/notice")
        return send.call_args.args[0].headers

    def test_source_identity_and_text_formats_reach_transport(self):
        sent = self.fetch()
        self.assertEqual(sent["User-Agent"], http.USER_AGENT)
        self.assertEqual(sent["Accept"], "text/html,application/json,application/xml,text/plain;q=0.8,*/*;q=0.5")

    def test_case_insensitive_overrides_preserve_downloader_header_allowlist(self):
        sent = self.fetch({"user-agent": "Funding-Source-Audit/1.0", "accept": "application/json",
                           "If-None-Match": "source-version", "Authorization": "secret", "Cookie": "secret"})
        self.assertEqual(sent["User-Agent"], "Funding-Source-Audit/1.0")
        self.assertEqual(sent["Accept"], "application/json")
        self.assertEqual(sent["If-None-Match"], "source-version")
        self.assertNotIn("Authorization", sent)
        self.assertNotIn("Cookie", sent)

    def test_generic_document_defaults_are_unchanged(self):
        sent = self.fetch(document=True)
        self.assertEqual(sent["User-Agent"], documents.USER_AGENT)
        self.assertEqual(sent["Accept"], "application/pdf,text/html,text/plain;q=0.8,*/*;q=0.5")


if __name__ == "__main__":
    unittest.main()
