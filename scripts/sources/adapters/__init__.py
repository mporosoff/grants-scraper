"""Bundled source adapters.

Importing this package imports each adapter module, which registers its source
instances with the registry. New adapters are disabled by default; enable one
only after implementing and verifying it against its live source.

To add a source, copy ``_template.py`` and add an import line below.
"""

from . import rss            # noqa: F401  (Philanthropy News Digest RFP; disabled)
from . import sample         # noqa: F401  (offline demo/fixture adapter; disabled)
from . import nyserda        # noqa: F401  (verified state source; enabled)
from . import ur_infoready   # noqa: F401  (disabled shell; parser retained)
from . import doe_exchange   # noqa: F401  (ARPA-E + DOE EERE Exchange; enabled)
from . import nspires        # noqa: F401  (NASA NSPIRES; enabled)

__all__ = ["rss", "sample", "nyserda", "ur_infoready", "doe_exchange", "nspires"]
