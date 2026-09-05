import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.verify_researcher_publication import verify_profile


class ResearcherPublicationTests(unittest.TestCase):
    def setUp(self):
        self.generation = "a" * 64
        self.identity = "urh-000001"
        self.directory = {"registry_generation": self.generation, "researchers": [
            {"id": self.identity, "name": "Same Name", "status": "inactive",
             "pool_visibility": "hidden", "auto_proposable": False, "claims": [{"label": "Original evidence"}]},
            {"id": "urh-000002", "name": "Same Name", "status": "active"},
        ]}

    def test_removal_uses_stable_identity_and_exact_eligibility_without_a_submitted_name(self):
        verify_profile(self.directory, copy.deepcopy(self.directory), self.generation, self.identity)

    def test_nomination_and_name_correction_verify_the_generated_profile(self):
        for name in ("New Researcher", "Corrected Researcher Name"):
            expected = copy.deepcopy(self.directory)
            expected["researchers"][0].update(name=name, status="active", pool_visibility="department", auto_proposable=True)
            verify_profile(expected, copy.deepcopy(expected), self.generation, self.identity)
            with self.assertRaises(ValueError):
                verify_profile(expected, self.directory, self.generation, self.identity)

    def test_wrong_generation_missing_duplicate_and_changed_profiles_fail(self):
        variants = []
        for field, value in (("status", "active"), ("auto_proposable", True), ("pool_visibility", "department"),
                             ("claims", []), ("name", "Unexpected Name")):
            changed = copy.deepcopy(self.directory)
            changed["researchers"][0][field] = value
            variants.append(changed)
        variants.extend([
            {**self.directory, "registry_generation": "b" * 64},
            {**self.directory, "researchers": self.directory["researchers"][1:]},
            {**self.directory, "researchers": self.directory["researchers"] + [self.directory["researchers"][0]]},
        ])
        for live in variants:
            with self.subTest(live=live), self.assertRaises(ValueError):
                verify_profile(self.directory, live, self.generation, self.identity)
        for identity in ("", "null", "urh-999999"):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                verify_profile(self.directory, self.directory, self.generation, identity)
        with self.assertRaises(ValueError):
            verify_profile(self.directory, self.directory, "b" * 64, self.identity)

    def test_workflow_command_parses_public_javascript_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "directory.js"
            path.write_text("globalThis.RESEARCHER_DIRECTORY = " + json.dumps(self.directory) + ";", encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "scripts.verify_researcher_publication",
                                     "--expected-directory", str(path), "--live-directory", str(path),
                                     "--generation", self.generation, "--researcher-id", self.identity],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
