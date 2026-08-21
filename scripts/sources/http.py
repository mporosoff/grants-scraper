"""A small, polite HTTP helper for source adapters.

Mirrors the caution the Grants.gov enrichment step already uses: a descriptive
User-Agent, timeouts, a capped response size, and light rate-limiting. Adapters
that need the network use this; the framework and tests never touch it.
"""

from __future__ import annotations

import ssl
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

USER_AGENT = "Funding-Finder-Sources/1.0 (+https://mporosoff.github.io/grants-scraper/)"
DEFAULT_TIMEOUT = (15, 60)          # (connect, read) seconds
MAX_BYTES = 8 * 1024 * 1024         # 8 MB safety cap per response


# --- Per-source TLS compatibility (§17.11) -----------------------------------
#
# **Off by default, opt-in per adapter, and never a global.** A source that
# needs this must justify it with its own measurement; sharing `PoliteClient`
# is not a reason to inherit it.
#
# Measured 2026-08-17 against `solicitation.nasaprs.com` and
# `nspires.nasaprs.com`, isolation matrix in docs/ROSES_SOURCE_INSPECTION.md:
#
#   default context                            FAIL  SSLEOFError
#   set_ciphers("DEFAULT@SECLEVEL=2")          OK    TLSv1.2 / AES256-GCM-SHA384
#   set_ciphers("AES256-GCM-SHA384")           OK    TLSv1.2 / AES256-GCM-SHA384
#   python default suites + AES256-GCM-SHA384  OK    TLSv1.2 / AES256-GCM-SHA384
#
# **The security level was never the blocker**, which an earlier note in this
# project got wrong: SECLEVEL=2 succeeds. What blocks the handshake is that
# CPython's `create_default_context()` curates a 14-suite TLS<=1.2 list that
# omits `AES256-GCM-SHA384`, and these hosts offer nothing else.
#
# So the fix is additive and minimal: take CPython's own list and append that
# one suite. Measured effect -- exactly one suite added, none removed,
# `SECLEVEL` untouched, `verify_mode` and `check_hostname` unchanged.
#
# **What it costs, stated rather than glossed:** `AES256-GCM-SHA384` uses static
# RSA key exchange, so traffic to an opted-in host has **no forward secrecy**.
# That is why CPython drops it. It is acceptable for these hosts specifically --
# the request carries no secret, the response is a public solicitation table,
# and the certificate is still verified so the peer is authenticated. It would
# not be acceptable for a source carrying credentials.
LEGACY_RSA_SUITE = "AES256-GCM-SHA384"


def _compatible_cipher_string(extra_suite: str = LEGACY_RSA_SUITE) -> str:
    """CPython's default TLS<=1.2 suites, plus one, in that order.

    Built from the live default context rather than from a hand-copied string,
    so an interpreter upgrade that changes the defaults is inherited instead of
    silently overridden.
    """
    context = ssl.create_default_context()
    names = [
        cipher["name"]
        for cipher in context.get_ciphers()
        # set_ciphers() governs TLS<=1.2 only; TLS1.3 suites are fixed and the
        # setter rejects them.
        if cipher.get("protocol") != "TLSv1.3"
        and not cipher["name"].startswith("TLS_")
    ]
    if extra_suite not in names:
        names.append(extra_suite)
    return ":".join(names)


class _LegacyCipherAdapter(HTTPAdapter):
    """HTTPS adapter whose context adds one legacy suite. Verification stays on."""

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        context = ssl.create_default_context()          # verify + hostname ON
        context.set_ciphers(_compatible_cipher_string())
        kwargs["ssl_context"] = context
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize, block=block, **kwargs
        )


class PoliteClient:
    """Reusable session with sane defaults and a minimum delay between calls."""

    def __init__(
        self,
        request_delay: float = 0.5,
        timeout=DEFAULT_TIMEOUT,
        *,
        legacy_tls_ciphers: bool = False,
    ):
        """`legacy_tls_ciphers` is opt-in per adapter and defaults to off.

        Set it only for a host measured to need it, and record the measurement
        at the call site (§17.11). It adds exactly one TLS<=1.2 suite to
        CPython's default list; it does not lower the security level and does
        not weaken certificate or hostname verification.
        """
        self.request_delay = request_delay
        self.timeout = timeout
        self.legacy_tls_ciphers = legacy_tls_ciphers
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        if legacy_tls_ciphers:
            self._session.mount("https://", _LegacyCipherAdapter())
        self._last_call = 0.0
        self.last_url: Optional[str] = None

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
        # Preserve the authoritative post-redirect URL for adapters whose
        # source publishes version information in the resolved document name.
        self.last_url = response.url
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
