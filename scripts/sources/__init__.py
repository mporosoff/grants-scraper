"""Modular multi-source ingestion layer for Funding Finder.

This package lets Funding Finder pull opportunities from sources *beyond*
Grants.gov (state agencies like NYSERDA, foundation aggregators, university
InfoReady portals, RSS feeds, ...) without changing any existing pipeline
file.

How it fits in
--------------
The existing daily pipeline is unchanged::

    build_catalog.py  ->  enrich_catalog.py  ->  extract_document_evidence.py
        (Grants.gov)        (Grants.gov)              (Grants.gov)

This layer adds one final step that reads the generated
``data/opportunities.js``, refreshes records from enabled source adapters,
re-deduplicates, rebuilds the search index and facets with Grants.gov's own
functions, and writes the file back::

        ...  ->  python -m scripts.sources merge --write

Because it runs last, the Grants.gov steps never see external records. Each
enabled source publishes an atomic snapshot and falls back to its committed
last-known-good records when a refresh fails or looks unhealthy.

Safety by default
-----------------
New adapters start with ``enabled = False`` until implemented and verified
against their live source. Verified adapters are enabled one at a time.

Public API
----------
- ``CanonicalOpportunity`` / ``SourceAdapter`` -- what you implement per source.
- ``REGISTRY`` / ``register`` / ``collect`` -- adapter discovery and running.
- ``integrate`` -- the drop-in step that merges sources into the catalog.
"""

from .base import CanonicalOpportunity, SourceAdapter
from .registry import REGISTRY, register, collect
from .merge import integrate, load_catalog, merge_records

# Importing the adapters package self-registers the bundled adapters.
from . import adapters  # noqa: E402,F401  (import for side effect: registration)

__all__ = [
    "CanonicalOpportunity",
    "SourceAdapter",
    "REGISTRY",
    "register",
    "collect",
    "integrate",
    "load_catalog",
    "merge_records",
]
