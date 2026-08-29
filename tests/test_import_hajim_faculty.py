import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from scripts.import_hajim_faculty import (
    HEADERS,
    FacultyImportError,
    canonical_bytes,
    import_workbook,
    validate_payload,
)


ROOT = Path(__file__).resolve().parents[1]


class HajimFacultyImportTests(unittest.TestCase):
    def _row(self, **overrides):
        values = {
            "Faculty Name": "José Test",
            "Primary / Home Unit": "Electrical and Computer Engineering",
            "Faculty Relationship": "Hajim primary/core faculty",
            "Academic Rank / Appointments": "Professor; Director, Test Center",
            "Hajim Faculty Roster(s)": "Electrical and Computer Engineering; Materials Science",
            "Research Interests (website text, lightly normalized)": "Photonic sensing; machine learning",
            "Derived Research Theme(s)": "Optics / Photonics / Lasers; AI / ML / Data Science",
            "Email": "JOSE@ROCHESTER.EDU",
            "Lab / Faculty Website": "",
            "Source Faculty Page URL(s)": "https://example.edu/ece | https://example.edu/materials",
            "Checked Date": "2026-08-28",
        }
        values.update(overrides)
        return [values[header] for header in HEADERS]

    def _workbook(self, rows, headers=HEADERS):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "fixture.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Faculty Profiles"
        sheet.append(list(headers))
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        self.addCleanup(directory.cleanup)
        return path

    def test_exact_header_relationship_split_unicode_and_missing_interest_contract(self):
        decomposed = "Jose\u0301 Test"
        rows = [
            self._row(**{"Faculty Name": decomposed}),
            self._row(**{
                "Faculty Name": "No Interests",
                "Faculty Relationship": "Hajim research faculty",
                "Email": "none@rochester.edu",
                "Research Interests (website text, lightly normalized)": "Not listed on source faculty page",
            }),
        ]
        payload = import_workbook(self._workbook(rows), require_snapshot=False)
        first, second = payload["profiles"]
        self.assertEqual(first["name"], "José Test")
        self.assertEqual(first["email"], "jose@rochester.edu")
        self.assertEqual(first["appointments"], ["Professor", "Director, Test Center"])
        self.assertEqual(first["source_urls"], ["https://example.edu/ece", "https://example.edu/materials"])
        self.assertIsNone(first["website_url"])
        self.assertEqual(first["relationship"], "hajim_primary_core")
        self.assertFalse(second["rankable"])
        self.assertEqual(second["research_phrases"], [])
        validate_payload(payload)

    def test_rejects_header_drift_unknown_relationship_duplicate_email_and_non_https_source(self):
        bad_headers = list(HEADERS)
        bad_headers[0] = "Name"
        with self.assertRaises(FacultyImportError):
            import_workbook(self._workbook([self._row()], bad_headers), require_snapshot=False)

        unknown = self._row(**{"Faculty Relationship": "Visiting faculty"})
        with self.assertRaises(FacultyImportError):
            import_workbook(self._workbook([unknown]), require_snapshot=False)

        duplicate = self._row(**{"Faculty Name": "Another Person"})
        with self.assertRaises(FacultyImportError):
            import_workbook(self._workbook([self._row(), duplicate]), require_snapshot=False)

        insecure = self._row(**{"Source Faculty Page URL(s)": "http://example.edu/faculty"})
        with self.assertRaises(FacultyImportError):
            import_workbook(self._workbook([insecure]), require_snapshot=False)

    def test_name_collision_gets_deterministic_email_suffix(self):
        rows = [
            self._row(**{"Email": "one@rochester.edu"}),
            self._row(**{"Email": "two@rochester.edu"}),
        ]
        payload = import_workbook(self._workbook(rows), require_snapshot=False)
        ids = [profile["faculty_id"] for profile in payload["profiles"]]
        self.assertEqual(ids[0], "jose-test")
        self.assertEqual(ids[1], "jose-test-" + hashlib.sha256(b"two@rochester.edu").hexdigest()[:8])

    def test_repeated_import_emits_identical_json_bytes(self):
        path = self._workbook([self._row()])
        first = canonical_bytes(import_workbook(path, require_snapshot=False))
        second = canonical_bytes(import_workbook(path, require_snapshot=False))
        self.assertEqual(first, second)

    def test_committed_snapshot_has_verified_contract(self):
        payload = json.loads((ROOT / "config" / "hajim_faculty.json").read_text(encoding="utf-8"))
        validate_payload(payload, require_snapshot=True)
        self.assertEqual(payload["source"]["sha256"], "f625ec89beabcfe7a7c178b83dcd9ca6737be455fc70c3b00f06882f2d6114fc")
        self.assertEqual(len(payload["profiles"]), 156)
        self.assertEqual(sum(profile["rankable"] for profile in payload["profiles"]), 145)


if __name__ == "__main__":
    unittest.main()
