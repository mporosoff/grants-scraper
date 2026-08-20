"""Hermetic tests for P9's one-pass frame and campaign."""

import unittest

from scripts import build_subtopics
from scripts import subtopic_records


def parent(identifier, *, close_date="2026-12-31"):
    return {
        "opportunity_id": identifier,
        "opportunity_number": f"TEST-{identifier}",
        "title": f"Parent {identifier}",
        "status": "posted",
        "close_date": close_date,
        "primary_document_url": f"https://example.test/{identifier}.pdf",
        "primary_document_name": f"{identifier}.pdf",
    }


class FrameTests(unittest.TestCase):
    def test_frame_freezes_only_current_parents(self):
        catalog = {"opportunities": [
            parent("active"),
            parent("expired", close_date="2020-01-01"),
        ]}
        frame = build_subtopics.frame_payload(
            catalog, {"records": {"active": {}}}, as_of="2026-08-20"
        )
        self.assertEqual(frame["current_parent_count"], 1)
        self.assertEqual(frame["excluded_parent_count"], 1)
        self.assertEqual(frame["population"][0]["opportunity_id"], "active")


class CampaignTests(unittest.TestCase):
    def test_campaign_walks_each_frozen_parent_once(self):
        calls = []

        def fetch(url, headers):
            calls.append((url, headers))
            return {
                "content": b"fixture",
                "content_type": "application/pdf",
                "url": url,
            }

        def containers(*_args):
            return ([{"page": 1, "text": "fixture"}], {})

        def fields(record, content, extracted, document, fetched_at, enabled):
            self.assertTrue(enabled)
            self.assertEqual(content, b"fixture")
            built = subtopic_records.build_structured_records(
                record,
                [{"code": "A", "title": "Catalysis", "text": "Catalysis"}],
                document=document,
                as_of=fetched_at[:10],
                provenance=subtopic_records.NATIVE,
                confidence="high",
                method="fixture_native",
                source_version=document["sha256"],
            )
            return {"subtopics": built, "subtopic_method": "fixture_native"}

        cache, metrics = build_subtopics.run_campaign(
            [parent("b"), parent("a")],
            fetcher=fetch,
            container_extractor=containers,
            field_builder=fields,
            request_delay=0,
        )
        self.assertEqual(metrics["attempted_parent_count"], 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sorted(cache["records"]), ["a", "b"])
        self.assertEqual(subtopic_records.sidecar_payload(cache)["record_count"], 2)
        self.assertEqual(
            subtopic_records.sidecar_payload(cache)["searchable_record_count"], 2
        )

    def test_validation_rejects_a_child_bound_to_another_parent(self):
        cache = {
            "records": {
                "a": {"subtopics": [{
                    "subtopic_id": "a:x",
                    "parent_id": "b",
                    "child_type": "subject",
                    "summary": "x",
                    "subtopic_terms": {},
                    "source_document_hash": "hash",
                }]}
            }
        }
        self.assertIn("wrong_parent:a:x", build_subtopics.validate_cache(cache, {"a"}))


if __name__ == "__main__":
    unittest.main()
