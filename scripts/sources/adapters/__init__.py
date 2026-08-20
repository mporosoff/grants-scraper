"""Bundled source adapters.

Importing this package imports each adapter module, which registers its source
instances with the registry. New adapters are disabled by default; enable one
only after implementing and verifying it against its live source.

To add a source, copy ``_template.py`` and add an import line below.
"""

from . import rss            # noqa: F401  (Philanthropy News Digest RFP; disabled)
from . import nsf_cbet       # noqa: F401  (official current CBET clusters)
from . import sample         # noqa: F401  (offline demo/fixture adapter; disabled)
from . import nyserda        # noqa: F401  (verified state source; enabled)
from . import ur_infoready   # noqa: F401  (disabled shell; parser retained)
from . import doe_exchange   # noqa: F401  (ARPA-E + DOE EERE Exchange; enabled)
from . import nspires        # noqa: F401  (NASA NSPIRES; disabled shell)
from . import vpr_email      # noqa: F401  (VPR email digest)
from . import jhu_fellowships  # noqa: F401  (JHU RDT fellowship lists)
from . import nasa_roses  # noqa: F401  (NASA ROSES native; disabled)
from . import arpa_h  # noqa: F401  (official ARPA-H current opportunities)

__all__ = ["rss", "nsf_cbet", "sample", "nyserda", "ur_infoready", "doe_exchange",
           "nspires", "vpr_email", "jhu_fellowships", "nasa_roses", "arpa_h"]
