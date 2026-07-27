"""NASA NSPIRES research solicitations (nspires.nasaprs.com).

Disabled shell. NASA is already partially covered via Grants.gov (~18 records),
and NSPIRES's public "Open Solicitations" list is not a simple server-rendered
page: the ``solicitations!init.do`` entry point returns only a privacy/policy
splash, and the actual list is produced by a session/POST search flow. Until a
stable, fetchable list endpoint is confirmed (and the ROSES omnibus is handled
so individual program-element "Appendices" are surfaced rather than duplicated),
this adapter stays off.

The parser below expects a NSPIRES solicitation-row shape once a working list
response is captured; it is retained for that future work.
"""

from __future__ import annotations

from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..registry import register

LIST_URL = "https://nspires.nasaprs.com/external/solicitations/solicitations!init.do"


class NspiresAdapter(SourceAdapter):
    slug = "nasa-nspires"
    display_name = "NASA NSPIRES"
    source_type = "Federal"
    enabled = False
    min_records = 1
    max_records = 800

    def fetch(self):
        raise RuntimeError(
            "NASA NSPIRES is a disabled shell: its open-solicitations list is "
            "session-gated and no stable public list endpoint is confirmed yet."
        )

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        # Placeholder for when a real NSPIRES list response is captured.
        return []


register(NspiresAdapter())
