"""Bundled source adapters.

Importing this package imports each adapter module, which registers its source
instances with the registry. New adapters are disabled by default; enable one
only after implementing and verifying it against its live source.

To add a source, copy ``_template.py`` and add an import line below.
"""

from . import rss            # noqa: F401  (Philanthropy News Digest RFP; disabled)
from . import sample         # noqa: F401  (offline demo/fixture adapter; disabled)
from . import nyserda        # noqa: F401  (scaffold; disabled)
from . import ur_infoready   # noqa: F401  (scaffold; disabled)

__all__ = ["rss", "sample", "nyserda", "ur_infoready"]
