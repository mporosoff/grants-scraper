import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.faculty_match import (
    DIRECTORY_GZIP_BUDGET,
    DIRECTORY_RAW_BUDGET,
    GRAPH_GZIP_BUDGET,
    GRAPH_RAW_BUDGET,
    LONG_PHRASE_MIN_WINDOW,
    LONG_PHRASE_WINDOW_FACTOR,
    MAX_FACULTY_PER_OPPORTUNITY,
    MAX_OPPORTUNITIES_PER_FACULTY,
    _faculty_idf,
    _distinctive_tokens,
    _excerpt,
    _generation_id,
    _load_js_object,
    _projection_fingerprint,
    generate_assets,
    load_curated_cheme_config,
    load_faculty_config,
    merge_faculty_sources,
    score_profile_opportunity,
    validate_assets,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "hajim_faculty.json"
CURATED = ROOT / "config" / "cheme_team_match_profiles.json"
CATALOG = ROOT / "data" / "opportunities.js"
DIRECTORY = ROOT / "data" / "hajim_faculty_directory.js"
GRAPH = ROOT / "data" / "faculty_matches.js"
QUALITY = ROOT / "tests" / "fixtures" / "hajim_relevance_quality.json"


class FacultyMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workbook, workbook_raw = load_faculty_config(CONFIG)
        curated, curated_raw = load_curated_cheme_config(CURATED)
        cls.workbook = workbook
        cls.curated = curated
        cls.config = merge_faculty_sources(workbook, workbook_raw, curated, curated_raw)
        cls.directory, _ = _load_js_object(DIRECTORY, "HAJIM_FACULTY_DIRECTORY")
        cls.graph, _ = _load_js_object(GRAPH, "FACULTY_MATCHES")

    def test_generated_assets_share_one_current_identity(self):
        validate_assets(self.directory, self.graph)
        self.assertEqual(self.directory["generation_id"], self.graph["generation_id"])
        self.assertEqual(self.directory["asset_version"], self.directory["generation_id"])
        self.assertEqual(self.directory["projection_fingerprints"], self.graph["projection_fingerprints"])
        self.assertEqual(self.directory["faculty_source"], self.graph["faculty_source"])
        self.assertEqual(self.directory["catalog"], self.graph["catalog"])
        source = self.directory["faculty_source"]
        self.assertEqual(source["workbook"]["record_count"], 156)
        self.assertEqual(source["workbook"]["rankable_record_count"], 145)
        self.assertEqual(source["workbook"]["unlisted_interest_count"], 11)
        self.assertEqual(source["union_record_count"], 158)
        self.assertEqual(source["union_rankable_record_count"], 148)
        self.assertEqual(source["union_unrankable_count"], 10)

    def test_identity_changes_with_either_projection_and_rejects_tampering(self):
        directory_fingerprint = _projection_fingerprint(self.directory)
        graph_fingerprint = _projection_fingerprint(self.graph)
        self.assertEqual(directory_fingerprint, self.directory["projection_fingerprints"]["directory"])
        self.assertEqual(graph_fingerprint, self.directory["projection_fingerprints"]["graph"])
        changed_graph = copy.deepcopy(self.graph)
        changed_graph["edges"][0]["score"] += 0.001
        changed_fingerprints = {
            "directory": directory_fingerprint,
            "graph": _projection_fingerprint(changed_graph),
        }
        changed_generation = _generation_id(
            self.directory["faculty_source"]["source_fingerprint"],
            self.directory["catalog"]["fingerprint"],
            changed_fingerprints,
        )
        self.assertNotEqual(changed_generation, self.directory["generation_id"])
        with self.assertRaisesRegex(ValueError, "fingerprints"):
            validate_assets(self.directory, changed_graph)

    def test_edges_are_normalized_bounded_and_exclude_unrankable_profiles(self):
        edges = self.graph["edges"]
        self.assertEqual(len(edges), len({(edge["faculty_id"], edge["opportunity_id"]) for edge in edges}))
        self.assertTrue(all(len(indexes) <= MAX_FACULTY_PER_OPPORTUNITY
                            for indexes in self.graph["by_opportunity"].values()))
        self.assertTrue(all(len(indexes) <= MAX_OPPORTUNITIES_PER_FACULTY
                            for indexes in self.graph["by_faculty"].values()))
        unrankable = {profile["faculty_id"] for profile in self.directory["profiles"] if not profile["rankable"]}
        self.assertFalse(unrankable & set(self.graph["by_faculty"]))
        self.assertEqual(
            sorted(index for values in self.graph["by_opportunity"].values() for index in values),
            list(range(len(edges))),
        )
        metrics = self.graph["generation_metrics"]
        self.assertEqual(metrics["edge_count"], len(edges))
        actual_field_counts = {}
        actual_field_sets = {}
        for edge in edges:
            fields = sorted({item["field"] for item in edge["opportunity_evidence"]})
            field_set = "+".join(fields)
            actual_field_sets[field_set] = actual_field_sets.get(field_set, 0) + 1
            for field in fields:
                actual_field_counts[field] = actual_field_counts.get(field, 0) + 1
        self.assertEqual(metrics["evidence_field_edge_counts"], actual_field_counts)
        self.assertEqual(metrics["evidence_field_sets"], actual_field_sets)
        baseline = self.graph["admission_audit_baseline"]
        self.assertEqual(baseline["edge_count"], 918)
        self.assertEqual(baseline["evidence_field_sets"]["published_subject"], 164)
        self.assertLess(len(edges), baseline["edge_count"])
        self.assertEqual(
            self.graph["matching_policy"]["corroborating_only_fields"],
            ["disciplines", "topic_areas", "derived_themes"],
        )

    def test_directory_search_documents_preserve_official_phrase_boundaries(self):
        canonical = {profile["faculty_id"]: profile for profile in self.config["profiles"]}
        for projection in self.directory["profiles"]:
            source = canonical[projection["faculty_id"]]
            expected = "; ".join(
                " ".join(str(phrase).split()).casefold()
                for phrase in source.get("research_phrases", [])
                if str(phrase).strip()
            ) if source.get("rankable") else ""
            self.assertEqual(projection["search_document"], expected)

    def test_protected_cheme_profiles_are_preserved_in_one_deduplicated_union(self):
        protected_names = [
            "Mitchell Anthamatten", "Yasemin Basdogan", "Pooja Rajendra Bhalode",
            "Siddharth Deshpande", "Gang Fan", "David G. Foster",
            "Melodie I. Lawton", "Darren Lipomi", "Allison J. Lopatkin",
            "Astrid M. Muller", "Marc D. Porosoff", "Alexander A. Shestopalov",
            "Wyatt E. Tenhaeff", "Matthew Z. Yates",
        ]
        self.assertEqual([profile["name"] for profile in self.curated["profiles"]], protected_names)
        protected_rows = [{
            key: profile[key]
            for key in ("faculty_id", "name", "aliases", "research_phrases", "research_summary", "domains")
        } for profile in self.curated["profiles"]]
        digest = hashlib.sha256(json.dumps(
            protected_rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")).hexdigest()
        self.assertEqual(digest, "e8623811298848422671a33319bb7e5e551c40f041e225a2773ebe50694150c4")
        by_id = {profile["faculty_id"]: profile for profile in self.config["profiles"]}
        self.assertEqual(len(by_id), 158)
        self.assertEqual(sum(profile["workbook_member"] for profile in by_id.values()), 156)
        for faculty_id in ("david-g-foster", "melodie-i-lawton"):
            self.assertFalse(by_id[faculty_id]["workbook_member"])
            self.assertEqual(by_id[faculty_id]["roster_provenance"], ["curated_cheme_team_match_compatibility"])
        self.assertTrue(by_id["darren-lipomi"]["rankable"])
        self.assertFalse(by_id["darren-lipomi"]["workbook_rankable"])
        self.assertEqual(by_id["darren-lipomi"]["expertise_provenance"], "curated_cheme_team_match_compatibility")
        self.assertIn("Astrid M. Muller", by_id["astrid-m-muller"]["aliases"])
        self.assertEqual(len([profile for profile in by_id.values() if profile["faculty_id"] == "astrid-m-muller"]), 1)

    def test_legacy_cheme_profiles_remain_matchable_on_fixed_authoritative_fixtures(self):
        profiles = self.config["profiles"]
        by_id = {profile["faculty_id"]: profile for profile in profiles}
        idf = _faculty_idf(profiles)
        cases = {
            "david-g-foster": {
                "opportunity_id": "legacy-foster",
                "title": "Computational fluid dynamics for circulating cancer-cell capture",
                "description": "Transport phenomena and nanoparticle capture coatings in microfluidic systems.",
            },
            "melodie-i-lawton": {
                "opportunity_id": "legacy-lawton",
                "title": "Controlled drug delivery with shape-memory polymers",
                "description": "Polymeric composites and structure-property relationships for biomaterials.",
            },
            "darren-lipomi": {
                "opportunity_id": "legacy-lipomi",
                "title": "Organic and flexible electronics",
                "description": "Conducting polymers and stretchable semiconductors for wearable bioelectronic interfaces.",
            },
        }
        for faculty_id, opportunity in cases.items():
            with self.subTest(faculty_id=faculty_id):
                edge = score_profile_opportunity(by_id[faculty_id], opportunity, idf)
                self.assertIsNotNone(edge)
                self.assertTrue(edge["matched_profile_phrases"])

    def test_generic_or_theme_only_overlap_cannot_admit(self):
        profile = {
            "faculty_id": "generic",
            "rankable": True,
            "research_interests_text": "materials; energy; research systems",
            "research_phrases": ["materials", "energy", "research systems"],
            "derived_themes": ["Materials / Polymers / Nanoscience"],
        }
        opportunity = {
            "opportunity_id": "generic-opportunity",
            "title": "Materials and energy research systems",
            "description": "A broad program for materials, energy, data, and health.",
            "topic_areas": ["Materials / Polymers / Nanoscience"],
        }
        self.assertIsNone(score_profile_opportunity(profile, opportunity, {}))

    def test_opportunity_facets_and_generic_single_terms_cannot_admit(self):
        profiles = self.config["profiles"]
        by_id = {profile["faculty_id"]: profile for profile in profiles}
        idf = _faculty_idf(profiles)
        facet_only = {
            "opportunity_id": "facet-only-ai",
            "title": "General collaborative program",
            "description": "Supports broad interdisciplinary activities.",
            "disciplines": ["Engineering and Physical Sciences"],
            "topic_areas": ["Artificial intelligence and machine learning", "Reasoning"],
        }
        self.assertIsNone(score_profile_opportunity(by_id["hangfeng-he"], facet_only, idf))
        generic_profile = {
            "faculty_id": "generic-single",
            "rankable": True,
            "research_interests_text": "optimization; routing; reasoning",
            "research_phrases": ["optimization", "routing", "reasoning"],
            "derived_themes": ["Artificial intelligence and machine learning"],
        }
        generic_idf = {"optimization": 5.0, "routing": 5.0, "reasoning": 5.0}
        for term in ("optimization", "routing", "reasoning"):
            with self.subTest(term=term):
                self.assertIsNone(score_profile_opportunity(generic_profile, {
                    "opportunity_id": f"generic-{term}",
                    "title": term.title(),
                    "description": "A broad research program.",
                }, generic_idf))

    def test_specific_authoritative_text_still_admits_and_facets_only_corroborate(self):
        profiles = self.config["profiles"]
        by_id = {profile["faculty_id"]: profile for profile in profiles}
        idf = _faculty_idf(profiles)
        record = {
            "opportunity_id": "specific-spintronics",
            "title": "Spintronics research initiative",
            "description": "Experimental work on magnetic heterostructures.",
            "topic_areas": ["Materials science"],
        }
        edge = score_profile_opportunity(by_id["stephen-wu"], record, idf)
        self.assertIsNotNone(edge)
        self.assertTrue(any(item["field"] == "title" for item in edge["opportunity_evidence"]))

    def test_multiconcept_phrase_admits_with_local_evidence(self):
        profiles = self.config["profiles"]
        by_id = {profile["faculty_id"]: profile for profile in profiles}
        idf = _faculty_idf(profiles)
        record = {
            "opportunity_id": "catalysis-fixture",
            "title": "Carbon dioxide capture and conversion",
            "description": "Heterogeneous thermal catalysis for reactive separations.",
        }
        edge = score_profile_opportunity(by_id["marc-d-porosoff"], record, idf)
        self.assertIsNotNone(edge)
        self.assertIn("carbon dioxide capture and conversion", edge["matched_profile_phrases"])
        self.assertTrue(edge["opportunity_evidence"])

    def test_long_phrase_requires_every_concept_in_one_bounded_window(self):
        profile = {
            "faculty_id": "quantum-fixture",
            "rankable": True,
            "research_interests_text": "Experimental quantum information processing",
            "research_phrases": ["Experimental quantum information processing"],
            "derived_themes": [],
        }
        idf = {token: 3.0 for token in _distinctive_tokens(profile["research_interests_text"])}
        missing_defining_concept = {
            "opportunity_id": "missing-quantum",
            "title": "General research methods",
            "document_search_text": (
                "Experimental studies describe information from many unrelated sections. "
                + "administrative process " * 80
            ),
        }
        scattered_concepts = {
            "opportunity_id": "scattered-quantum",
            "description": (
                "Experimental work begins here. "
                + "background " * (LONG_PHRASE_MIN_WINDOW + 2)
                + "Quantum methods produce information for processing."
            ),
        }
        local_concepts = {
            "opportunity_id": "local-quantum",
            "description": "The program supports experimental quantum information processing platforms.",
        }
        self.assertIsNone(score_profile_opportunity(profile, missing_defining_concept, idf))
        self.assertIsNone(score_profile_opportunity(profile, scattered_concepts, idf))
        edge = score_profile_opportunity(profile, local_concepts, idf)
        self.assertIsNotNone(edge)
        self.assertEqual(edge["matched_profile_phrases"], ["Experimental quantum information processing"])
        self.assertIn("experimental quantum information processing", edge["opportunity_evidence"][0]["excerpt"].casefold())
        self.assertEqual(LONG_PHRASE_WINDOW_FACTOR, 3)
        self.assertEqual(LONG_PHRASE_MIN_WINDOW, 12)

    def test_reported_quantum_false_positive_is_absent_from_generated_graph(self):
        self.assertFalse(any(
            edge["faculty_id"] == "john-m-nichol"
            and edge["opportunity_id"] == "350944"
            and "Experimental quantum information processing" in edge["matched_profile_phrases"]
            for edge in self.graph["edges"]
        ))
        self.assertEqual(
            self.graph["matching_policy"]["long_phrase_policy"],
            "all_distinctive_concepts_within_bounded_token_window",
        )

    def test_excerpt_uses_the_matching_token_normalizer_for_word_forms(self):
        text = (
            "An unrelated opening section precedes the evidence by enough words to force clipping. "
            + "background " * 20
            + "The program develops mathematical theories and methodologies. "
            + "additional material " * 20
            + "Important information appears in a later administrative section."
        )
        excerpt = _excerpt(text, _distinctive_tokens("Information theory"), limit=120)
        self.assertIn("mathematical theories", excerpt)
        self.assertNotIn("unrelated opening", excerpt)

        graph_edge = next(
            edge for edge in self.graph["edges"]
            if edge["opportunity_id"] == "341997"
            and "Information theory" in edge["matched_profile_phrases"]
        )
        evidence = next(item for item in graph_edge["opportunity_evidence"] if item["field"] == "description")
        self.assertIn("theories", evidence["excerpt"].casefold())
        self.assertNotIn("supports research in all areas", evidence["excerpt"].casefold())

    def test_human_reviewed_multidisciplinary_quality_fixture(self):
        fixture = json.loads(QUALITY.read_text(encoding="utf-8"))
        profiles = self.config["profiles"]
        by_id = {profile["faculty_id"]: profile for profile in profiles}
        idf = _faculty_idf(profiles)
        self.assertGreaterEqual(len({case["discipline"] for case in fixture["cases"]}), 8)
        failures = []
        for case in fixture["cases"]:
            scores = {
                faculty_id: score_profile_opportunity(by_id[faculty_id], case["opportunity"], idf)
                for faculty_id in case["expected_profile_ids"] + case["irrelevant_near_neighbors"]
            }
            for faculty_id in case["expected_profile_ids"]:
                if scores[faculty_id] is None:
                    failures.append(f"{case['id']}: expected {faculty_id} was not admitted")
            expected_scores = [scores[item]["score"] for item in case["expected_profile_ids"] if scores[item]]
            for faculty_id in case["irrelevant_near_neighbors"]:
                irrelevant = scores[faculty_id]
                if irrelevant and (not expected_scores or irrelevant["score"] >= max(expected_scores)):
                    failures.append(f"{case['id']}: near-neighbor {faculty_id} outranked expected profile")
        self.assertEqual(failures, [])

    def test_assets_stay_within_explicit_raw_and_gzip_budgets(self):
        directory_bytes = DIRECTORY.read_bytes()
        graph_bytes = GRAPH.read_bytes()
        self.assertLessEqual(len(directory_bytes), DIRECTORY_RAW_BUDGET)
        self.assertLessEqual(len(gzip.compress(directory_bytes, mtime=0)), DIRECTORY_GZIP_BUDGET)
        self.assertLessEqual(len(graph_bytes), GRAPH_RAW_BUDGET)
        self.assertLessEqual(len(gzip.compress(graph_bytes, mtime=0)), GRAPH_GZIP_BUDGET)

    def test_repeated_generation_is_byte_for_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first_directory = Path(directory) / "first-directory.js"
            first_graph = Path(directory) / "first-graph.js"
            second_directory = Path(directory) / "second-directory.js"
            second_graph = Path(directory) / "second-graph.js"
            generate_assets(CONFIG, CATALOG, first_directory, first_graph)
            generate_assets(CONFIG, CATALOG, second_directory, second_graph)
            self.assertEqual(first_directory.read_bytes(), second_directory.read_bytes())
            self.assertEqual(first_graph.read_bytes(), second_graph.read_bytes())

    def test_generation_updates_page_markers_and_team_directory_version_together(self):
        old_generation = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finder = root / "match_explorer.html"
            team = root / "team_match.html"
            finder.write_text(
                f'<meta name="hajim-match-generation" content="{old_generation}" />\n',
                encoding="utf-8",
            )
            team.write_text(
                f'<meta name="hajim-match-generation" content="{old_generation}" />\n'
                f'<script src="data/hajim_faculty_directory.js?v={old_generation}"></script>\n',
                encoding="utf-8",
            )
            directory_out = root / "directory.js"
            graph_out = root / "graph.js"
            generated_directory, _ = generate_assets(
                CONFIG, CATALOG, directory_out, graph_out, (finder, team),
            )
            generation = generated_directory["generation_id"]
            self.assertNotEqual(generation, old_generation)
            self.assertIn(f'content="{generation}"', finder.read_text(encoding="utf-8"))
            team_text = team.read_text(encoding="utf-8")
            self.assertIn(f'content="{generation}"', team_text)
            self.assertIn(f'data/hajim_faculty_directory.js?v={generation}', team_text)

    def test_nightly_refresh_uses_canonical_config_and_atomic_outputs(self):
        workflow = (ROOT / ".github" / "workflows" / "refresh-opportunities.yml").read_text(encoding="utf-8")
        self.assertIn("python -m scripts.faculty_match match", workflow)
        self.assertIn("--faculty-config config/hajim_faculty.json", workflow)
        self.assertIn("--curated-cheme-config config/cheme_team_match_profiles.json", workflow)
        self.assertIn("--directory-out data/hajim_faculty_directory.js", workflow)
        self.assertIn("--version-target match_explorer.html", workflow)
        self.assertIn("--version-target team_match.html", workflow)
        self.assertIn("data/hajim_faculty_directory.js?v=${faculty_generation}", workflow)
        self.assertIn("data/faculty_matches.js?v=${faculty_generation}", workflow)
        self.assertNotIn("--profiles faculty_profiles.json", workflow)
        self.assertLess(
            workflow.index("- name: Rotate through official links and record health and redirects"),
            workflow.index("- name: Rebuild Hajim faculty directory and match graph atomically"),
        )


if __name__ == "__main__":
    unittest.main()
