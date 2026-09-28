"""Hermetic contracts for catalog freshness provenance and the daily window."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.scheduled_catalog import catalog_generated_at, daily_window


class ScheduledCatalogReader(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'data/catalog-metadata.js'
        self.path.parent.mkdir()

    def write_metadata(self, metadata=None, *, raw=None, comment=True):
        if raw is None:
            if metadata is None:
                metadata = {'schema_version': 1, 'generated_at': '2026-09-28T10:18:00Z'}
            prefix = '/* Generated with data/opportunities.js. Do not edit by hand. */\r\n' if comment else ''
            raw = (prefix + 'globalThis.GRANT_CATALOG_METADATA=' +
                   json.dumps(metadata, separators=(',', ':')) + ';\r\n').encode('utf-8')
        self.path.write_bytes(raw)
        return {'files': {'data/catalog-metadata.js': hashlib.sha256(raw).hexdigest()}}

    def test_reads_source_generation_time_even_when_pipeline_generation_is_newer(self):
        manifest = self.write_metadata({
            'schema_version': 1,
            'generated_at': '2026-09-27T10:18:00Z',
            'pipeline_generated_at': '2026-09-28T10:30:00Z',
        })
        manifest['generated_at'] = '2026-09-28T10:31:00Z'
        self.assertEqual(catalog_generated_at(self.root, manifest), '2026-09-27T10:18:00Z')

    def test_accepts_canonical_assignment_with_or_without_generated_comment(self):
        for comment in (True, False):
            with self.subTest(comment=comment):
                manifest = self.write_metadata(comment=comment)
                self.assertEqual(catalog_generated_at(self.root, manifest), '2026-09-28T10:18:00Z')

    def test_normalizes_timezone_offsets_to_utc_and_preserves_precision(self):
        for value, expected in (
            ('2026-09-28T06:18:00-04:00', '2026-09-28T10:18:00Z'),
            ('2026-09-28T15:48:00+05:30', '2026-09-28T10:18:00Z'),
            ('2026-09-28T00:15:00+02:00', '2026-09-27T22:15:00Z'),
            ('2026-09-28T10:18:00.123456+00:00', '2026-09-28T10:18:00.123456Z'),
        ):
            with self.subTest(value=value):
                manifest = self.write_metadata({'schema_version': 1, 'generated_at': value})
                self.assertEqual(catalog_generated_at(self.root, manifest), expected)

    def test_requires_manifest_digest(self):
        self.write_metadata()
        for manifest in ({}, {'files': {}}, {'files': {'data/catalog-metadata.js': ''}}):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                catalog_generated_at(self.root, manifest)

    def test_requires_metadata_file(self):
        manifest = self.write_metadata()
        self.path.unlink()
        with self.assertRaises(ValueError):
            catalog_generated_at(self.root, manifest)

    def test_checks_exact_file_bytes_before_trusting_date(self):
        manifest = self.write_metadata()
        # Semantically equivalent line endings still describe different artifact bytes.
        self.path.write_bytes(self.path.read_bytes().replace(b'\r\n', b'\n'))
        with self.assertRaises(ValueError):
            catalog_generated_at(self.root, manifest)

    def test_rejects_hash_mismatch(self):
        manifest = self.write_metadata()
        manifest['files']['data/catalog-metadata.js'] = '0' * 64
        with self.assertRaises(ValueError):
            catalog_generated_at(self.root, manifest)

    def test_does_not_substitute_pipeline_date_for_missing_source_date(self):
        manifest = self.write_metadata({
            'schema_version': 1, 'pipeline_generated_at': '2026-09-28T10:30:00Z',
        })
        with self.assertRaises(ValueError):
            catalog_generated_at(self.root, manifest)

    def test_requires_supported_metadata_schema(self):
        for metadata in (
            {'generated_at': '2026-09-28T10:18:00Z'},
            {'schema_version': 2, 'generated_at': '2026-09-28T10:18:00Z'},
        ):
            with self.subTest(metadata=metadata):
                manifest = self.write_metadata(metadata)
                with self.assertRaises(ValueError):
                    catalog_generated_at(self.root, manifest)

    def test_rejects_invalid_or_timezone_free_source_dates(self):
        for value in (None, '', 123, 'not-a-date', '2026-13-28T10:18:00Z',
                      '2026-09-28', '2026-09-28T10:18:00'):
            with self.subTest(value=value):
                manifest = self.write_metadata({'schema_version': 1, 'generated_at': value})
                with self.assertRaises(ValueError):
                    catalog_generated_at(self.root, manifest)

    def test_rejects_malformed_metadata_assignment(self):
        for raw in (
            b'globalThis.GRANT_CATALOG_METADATA={not-json};',
            b'globalThis.OTHER_METADATA={"schema_version":1,"generated_at":"2026-09-28T10:18:00Z"};',
            b'{"schema_version":1,"generated_at":"2026-09-28T10:18:00Z"}',
        ):
            with self.subTest(raw=raw):
                manifest = self.write_metadata(raw=raw)
                with self.assertRaises(ValueError):
                    catalog_generated_at(self.root, manifest)


class DailyCatalogWindow(unittest.TestCase):
    def test_window_rolls_over_at_exactly_1017_utc(self):
        today = datetime(2026, 9, 28, 10, 17, tzinfo=timezone.utc)
        for now, expected in (
            (today - timedelta(microseconds=1), today - timedelta(days=1)),
            (today, today),
            (today + timedelta(microseconds=1), today),
        ):
            with self.subTest(now=now):
                self.assertEqual(daily_window(now), expected)

    def test_midnight_retains_previous_window_across_calendar_boundaries(self):
        for now, expected in (
            (datetime(2026, 9, 29, tzinfo=timezone.utc), datetime(2026, 9, 28, 10, 17, tzinfo=timezone.utc)),
            (datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 9, 30, 10, 17, tzinfo=timezone.utc)),
            (datetime(2027, 1, 1, tzinfo=timezone.utc), datetime(2026, 12, 31, 10, 17, tzinfo=timezone.utc)),
        ):
            with self.subTest(now=now):
                self.assertEqual(daily_window(now), expected)

    def test_uses_utc_boundary_for_timezone_aware_inputs(self):
        local = datetime(2026, 9, 28, 6, 17, tzinfo=timezone(timedelta(hours=-4)))
        result = daily_window(local)
        self.assertEqual(result, datetime(2026, 9, 28, 10, 17, tzinfo=timezone.utc))
        self.assertEqual(result.utcoffset(), timedelta(0))


if __name__ == '__main__':
    unittest.main()
