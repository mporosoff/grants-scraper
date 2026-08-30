import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import faculty_match
from scripts.hajim_faculty_directory import (
    CURATED_PROFILE_KEYS,
    DirectoryContractError,
    EXPECTED_COUNTS,
    EXPECTED_SOURCE_SHA256,
    GZIP_SIZE_BUDGET,
    RAW_SIZE_BUDGET,
    asset_bytes,
    parse_asset,
    size_report,
    synchronize_html_generation,
    validate_payload,
)


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY_PATH = ROOT / "data" / "hajim-faculty-directory.js"


class HajimFacultyDirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asset = DIRECTORY_PATH.read_bytes()
        cls.payload = parse_asset(cls.asset)

    def test_committed_projection_is_canonical_and_within_budget(self):
        summary = validate_payload(self.payload)
        self.assertEqual(summary["source_sha256"], EXPECTED_SOURCE_SHA256)
        self.assertEqual(self.asset, asset_bytes(self.payload))
        raw, compressed = size_report(self.asset)
        self.assertLessEqual(raw, RAW_SIZE_BUDGET)
        self.assertLessEqual(compressed, GZIP_SIZE_BUDGET)

    def test_reviewed_workbook_counts_and_mapping_roles_are_frozen(self):
        self.assertEqual(self.payload["counts"], EXPECTED_COUNTS)
        terms = {item["id"]: item for item in self.payload["terms"]}
        primary = [mapping for profile in self.payload["profiles"] for mapping in profile["primary"]]
        context = [mapping for profile in self.payload["profiles"] for mapping in profile["context"]]
        self.assertEqual(len(primary), 460)
        self.assertEqual(len(context), 94)
        self.assertTrue(all(terms[item["term_id"]]["role"] == "primary_anchor" for item in primary))
        self.assertTrue(all(terms[item["term_id"]]["role"] == "supporting_context" for item in context))
        self.assertTrue(all(item["source_phrase"] and item["evidence"] for item in primary + context))

    def test_every_profile_is_searchable_and_fewer_than_five_anchors_is_valid(self):
        profiles = self.payload["profiles"]
        self.assertEqual(len(profiles), 157)
        self.assertTrue(all(profile["matching_available"] for profile in profiles))
        sparse = [profile for profile in profiles if len(profile["primary"]) < 5]
        self.assertGreater(len(sparse), 0)
        self.assertTrue(any(len(profile["primary"]) == 1 for profile in sparse))

    def test_curated_cheme_inputs_except_removed_identity_are_byte_frozen(self):
        curated = {
            name: {
                "key_terms": faculty_match.FACULTY_KEYTERMS[name],
                "summary": faculty_match.FACULTY_RESEARCH_SUMMARIES[name],
                "domains": faculty_match.FACULTY_DOMAINS[name],
            }
            for name in faculty_match.FACULTY
        }
        digest = hashlib.sha256(
            json.dumps(
                curated,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(tuple(faculty_match.FACULTY), CURATED_PROFILE_KEYS)
        self.assertEqual(digest, "6e11650474dc330aef2dd70012aa291e03c0c9f06cdbd6aedf670ec30b79819a")

    def test_removed_identity_is_absent_from_every_active_profile_asset(self):
        for path in (
            ROOT / "scripts" / "faculty_match.py",
            ROOT / "faculty_profiles.json",
            ROOT / "data" / "faculty_matches.js",
            DIRECTORY_PATH,
        ):
            text = path.read_text(encoding="utf-8").casefold()
            self.assertNotIn("melodie", text, path)
            self.assertNotIn("lawton", text, path)

    def test_directory_has_one_identity_for_each_curated_cheme_profile(self):
        mapped = [
            profile["curated_profile_key"]
            for profile in self.payload["profiles"]
            if profile["curated_profile_key"]
        ]
        self.assertCountEqual(mapped, CURATED_PROFILE_KEYS)
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertEqual(
            next(profile for profile in self.payload["profiles"] if profile["name"] == "Astrid M. Müller")["curated_profile_key"],
            "Astrid M. Muller",
        )

    def test_projection_contains_no_opportunity_graph(self):
        serialized = json.dumps(self.payload, sort_keys=True).casefold()
        self.assertNotIn("faculty_opportunity", serialized)
        self.assertNotIn("pi_matches", serialized)
        self.assertNotIn("edges", self.payload)
        self.assertNotIn("opportunities", self.payload)

    def test_html_generation_sync_writes_canonical_utf8_lf_bytes(self):
        identity = self.payload["generation_identity"]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "team_match.html"
            path.write_bytes(
                (
                    '<html>\r\n<meta name="hajim-faculty-directory-generation" '
                    f'content="{"0" * 64}" />\r\n</html>\r\n'
                ).encode("utf-8")
            )
            synchronize_html_generation(path, identity, write=True)
            expected = (
                '<html>\n<meta name="hajim-faculty-directory-generation" '
                f'content="{identity}" />\n</html>\n'
            ).encode("utf-8")
            self.assertEqual(path.read_bytes(), expected)
            synchronize_html_generation(path, identity, write=False)
            path.write_bytes(expected.replace(b"\n", b"\r\n"))
            with self.assertRaises(DirectoryContractError):
                synchronize_html_generation(path, identity, write=False)


if __name__ == "__main__":
    unittest.main()
