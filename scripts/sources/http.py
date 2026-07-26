"""A small, polite HTTP helper for source adapters.

Mirrors the caution the Grants.gov enrichment step already uses: a descriptive
User-Agent, timeouts, a capped response size, and light rate-limiting. Adapters
that need the network use this; the framework and tests never touch it.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

USER_AGENT = "Funding-Finder-Sources/1.0 (+https://mporosoff.github.io/grants-scraper/)"
DEFAULT_TIMEOUT = (15, 60)          # (connect, read) seconds
MAX_BYTES = 8 * 1024 * 1024         # 8 MB safety cap per response


class PoliteClient:
    """Reusable session with sane defaults and a minimum delay between calls."""

    def __init__(self, request_delay: float = 0.5, timeout=DEFAULT_TIMEOUT):
        self.request_delay = request_delay
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._last_call = 0.0

    def _pace(self) -> None:
        wait = self.request_delay - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def get_text(self, url: str, *, headers: Optional[dict] = None) -> str:
        """GET a URL and return decoded text, enforcing the size cap."""
        self._pace()
        response = self._session.get(
            url, headers=headers, timeout=self.timeout, stream=True
        )
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_BYTES:
                raise RuntimeError(f"Response from {url} exceeded {MAX_BYTES} bytes.")
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace")
