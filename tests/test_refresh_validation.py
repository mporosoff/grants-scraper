"""Contracts for the live generated-asset validation suite."""

import unittest

from tools import run_refresh_validation


class FrozenMeasurementSeparationTests(unittest.TestCase):
    def test_only_closed_catalog_bound_measurements_are_excluded(self):
        self.assertEqual(
            run_refresh_validation.FROZEN_MEASUREMENT_MODULES,
            {
                "test_meas8",
                "test_p5_closeout",
                "test_p7_frame",
                "test_p7_residual",
            },
        )

    def test_refresh_runner_keeps_ordinary_product_tests(self):
        modules = {
            test.__class__.__module__
            for test in run_refresh_validation.iter_tests(
                run_refresh_validation.live_refresh_suite()
            )
        }
        self.assertIn("test_document_evidence", modules)
        self.assertIn("test_p11_workflow", modules)
        self.assertFalse(modules & run_refresh_validation.FROZEN_MEASUREMENT_MODULES)


if __name__ == "__main__":
    unittest.main()
