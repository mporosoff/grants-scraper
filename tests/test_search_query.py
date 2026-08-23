"""Search-v2 browser/server query-plan and scope-entailment parity gates."""

from __future__ import annotations

import unittest

from scripts import build_catalog
from scripts.alert_match import hybrid_scores
from scripts.search_query import QUERY_API_CONTRACT_VERSION, expand_query_groups
from scripts.search_v2_contract import (
    load_search_v2_config,
    protected_rare_earth_evidence,
)


def _record(identifier: str, title: str = "Generic program", description: str = "") -> dict:
    return {
        "opportunity_id": identifier,
        "opportunity_number": f"TEST-{identifier}",
        "title": title,
        "agency": "Test agency",
        "topic_areas": [],
        "disciplines": ["Chemistry"],
        "funding_categories": ["Science"],
        "funding_instruments": ["Grant"],
        "applicant_types": ["Institutions of higher education"],
        "eligibility_text": "",
        "description": description,
        "document_search_text": "",
    }


def _catalog(records: list[dict]) -> dict:
    return {
        "schema_version": 3,
        "opportunities": records,
        "record_count": len(records),
        "search_index": build_catalog.build_search_index(records),
    }


class SearchV2ContractTests(unittest.TestCase):
    def test_query_plans_match_the_shared_browser_contract(self):
        specification = load_search_v2_config()
        self.assertEqual(
            QUERY_API_CONTRACT_VERSION,
            specification["compatibility"]["query_api_contract_version"],
        )
        for item in specification["query_contract_cases"]:
            with self.subTest(query=item["query"]):
                groups = expand_query_groups(item["query"], search_v2=True)
                self.assertEqual(
                    [group.get("concept_id") for group in groups],
                    item["concept_ids"],
                )

    def test_fielded_search_does_not_manufacture_scope_entailment(self):
        records = [
            _record("360678"),
            _record("361526"),
            _record("362061"),
            _record(
                "unmapped",
                "Critical minerals separations",
                "Research on critical minerals recovery.",
            ),
        ]
        scores, _, _ = hybrid_scores(_catalog(records), "REE separations", search_v2=True)
        admitted = {
            records[index]["opportunity_id"]
            for index, score in enumerate(scores)
            if score > 0
        }
        self.assertEqual(admitted, set())

        generic_scores, _, _ = hybrid_scores(
            _catalog(records),
            "critical mineral separations",
            search_v2=True,
        )
        self.assertEqual(generic_scores[0], 0)
        specification = load_search_v2_config()
        self.assertEqual(
            specification["fielded_ranking"]["architecture"],
            "bm25f_passage_coordination",
        )
        self.assertEqual(specification["concept_families"], [])
        self.assertEqual(specification["authoritative_scope_entailments"], [])

    def test_short_technical_query_and_acronym_metadata_match_browser_contract(self):
        minerals = expand_query_groups(
            "critical mineral separations",
            search_v2=True,
        )
        self.assertEqual(
            [group.get("concept_id") for group in minerals],
            ["critical-minerals", "separations"],
        )
        self.assertEqual(minerals[0].get("evidence_policy"), "controlled_compound")
        self.assertEqual(minerals[1].get("evidence_policy"), "technical_separation")

        navigation = expand_query_groups("quantum navigation", search_v2=True)
        self.assertIn(("pnt", 0.86), navigation[1]["terms"])

        acronym = expand_query_groups("CFD", postings={"cfd": [0, 1]}, search_v2=True)
        self.assertTrue(acronym[0]["exact_indexed_acronym"])

    def test_short_technical_admission_and_acronym_resolution_match_browser_contract(self):
        technical = _record(
            "technical",
            "Critical mineral separation research",
            "Chemical processing and recovery research for critical mineral resources.",
        )
        policy = _record(
            "policy",
            "Critical Minerals Policy Workshop",
            "A workshop on mineral supply policy and international coordination.",
        )
        cfd = _record(
            "cfd",
            "Computational fluid dynamics research",
            "CFD methods for turbulent transport.",
        )
        cfda = _record(
            "cfda",
            "CFDA assistance listing",
            "Federal assistance catalog information.",
        )
        catalog = _catalog([technical, policy, cfd, cfda])

        mineral_scores, _, _ = hybrid_scores(
            catalog,
            "critical mineral separations",
            search_v2=True,
        )
        self.assertGreater(mineral_scores[0], 0)
        self.assertEqual(mineral_scores[1], 0)

        acronym_scores, _, _ = hybrid_scores(catalog, "CFD", search_v2=True)
        self.assertGreater(acronym_scores[2], 0)
        self.assertEqual(acronym_scores[3], 0)

    def test_explicit_evidence_rejects_policy_and_lexical_collisions(self):
        technical = _record(
            "technical",
            "Rare earth separation research",
            "Fundamental chemical research on rare earth elements and solvent extraction.",
        )
        workshop = _record(
            "workshop",
            "Rare Earth Policy Workshop",
            "Training participants in advocacy and policy recommendations.",
        )
        nasa = _record(
            "nasa",
            "Earth Science Program Element",
            "Planetary and atmospheric research.",
        )
        self.assertIsNotNone(protected_rare_earth_evidence(technical))
        self.assertIsNone(protected_rare_earth_evidence(workshop))
        self.assertIsNone(protected_rare_earth_evidence(nasa))

        scores, _, _ = hybrid_scores(
            _catalog([technical, workshop, nasa]),
            "REE separations",
            search_v2=True,
        )
        self.assertGreater(scores[0], 0)
        self.assertEqual(scores[1:], [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
