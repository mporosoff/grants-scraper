"""Modular multi-source ingestion layer for Funding Finder.

This package lets Funding Finder pull opportunities from sources *beyond*
Grants.gov (state agencies like NYSERDA, foundation aggregators, university
InfoReady portals, RSS feeds, ...) without changing any existing pipeline
file.

How it fits in
--------------
The coordinated daily pipeline uses the existing components in this order::

    build_catalog.py -> enrich_catalog.py -> scripts.sources merge --write
       (Grants.gov)       (Grants.gov)        (canonical multi-source merge)
    -> extract_document_evidence.py -> faculty/team projections -> feeds/release
           (all canonical sources)

This layer reads the generated
``data/opportunities.js``, refreshes records from enabled source adapters,
re-deduplicates, rebuilds the search index and facets with Grants.gov's own
functions, and writes the file back. Shared official-document extraction then
finalizes evidence, eligible topics, searchable fields, indexes, and facets
before downstream consumers run. Each enabled source retains its own failure
policy and currentness gates. Developer-accepted inputs use the same lifecycle.

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
