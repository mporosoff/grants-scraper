"""Run post-refresh tests without redrawing closed measurement frames.

The scheduled refresh changes the live catalog and evidence cache.  P5, P7 and
MEAS-8 deliberately freeze historical sampling frames against the committed
pre-refresh inputs, so rerunning those modules after replacing their inputs
asks a different question and eventually fails as the funding universe moves.

The workflow runs the complete suite before refresh.  This runner then repeats
every non-historical test against the newly generated assets while leaving the
closed measurement artifacts and their assertions untouched.
"""

from __future__ import annotations

import sys
import unittest


FROZEN_MEASUREMENT_MODULES = frozenset({
    "test_meas8",
    "test_p5_closeout",
    "test_p7_frame",
    "test_p7_residual",
})


def iter_tests(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from iter_tests(test)
        else:
            yield test


def live_refresh_suite(start_dir="tests"):
    discovered = unittest.defaultTestLoader.discover(start_dir)
    selected = [
        test
        for test in iter_tests(discovered)
        if test.__class__.__module__ not in FROZEN_MEASUREMENT_MODULES
    ]
    return unittest.TestSuite(selected)


def main():
    suite = live_refresh_suite()
    excluded = ", ".join(sorted(FROZEN_MEASUREMENT_MODULES))
    print(
        "Post-refresh validation excludes closed frozen-measurement modules "
        f"already verified before refresh: {excluded}"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
