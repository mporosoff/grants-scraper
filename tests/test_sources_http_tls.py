"""Per-source TLS compatibility (§17.11). Offline: no host is contacted.

The point of these tests is that the ordinary `PoliteClient` is byte-for-byte
the client it always was, and that the opt-in adds exactly one cipher suite
without touching verification.
"""

import ssl
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from requests.adapters import HTTPAdapter  # noqa: E402

from scripts.sources import http  # noqa: E402


class DefaultClientIsUnchangedTests(unittest.TestCase):
    """The opt-in must be invisible unless a source asks for it."""

    def test_opt_in_defaults_to_off(self):
        self.assertFalse(http.PoliteClient().legacy_tls_ciphers)

    def test_default_client_mounts_no_custom_adapter(self):
        client = http.PoliteClient()
        adapter = client._session.get_adapter("https://example.org/")
        self.assertIsInstance(adapter, HTTPAdapter)
        self.assertNotIsInstance(adapter, http._LegacyCipherAdapter)

    def test_default_client_uses_the_stock_ssl_context(self):
        # A stock requests HTTPAdapter carries no ssl_context override, which is
        # what keeps the default path identical to every other adapter's.
        client = http.PoliteClient()
        adapter = client._session.get_adapter("https://example.org/")
        self.assertIsNone(
            getattr(adapter, "poolmanager", None).connection_pool_kw.get(
                "ssl_context"
            )
        )


class LegacyCipherOptInTests(unittest.TestCase):
    def test_opt_in_mounts_the_legacy_adapter(self):
        client = http.PoliteClient(legacy_tls_ciphers=True)
        adapter = client._session.get_adapter("https://example.org/")
        self.assertIsInstance(adapter, http._LegacyCipherAdapter)
        self.assertTrue(client.legacy_tls_ciphers)

    def test_it_adds_exactly_one_suite_and_removes_none(self):
        """The measured claim: additive, minimal, nothing dropped."""
        default = {
            cipher["name"]
            for cipher in ssl.create_default_context().get_ciphers()
            if cipher.get("protocol") != "TLSv1.3"
            and not cipher["name"].startswith("TLS_")
        }
        compatible = set(http._compatible_cipher_string().split(":"))
        self.assertEqual(compatible - default, {http.LEGACY_RSA_SUITE})
        self.assertEqual(default - compatible, set())

    def test_the_context_still_verifies_certificates_and_hostnames(self):
        """The security level is untouched; only the cipher list widens."""
        adapter = http._LegacyCipherAdapter()
        adapter.init_poolmanager(1, 1)
        context = adapter.poolmanager.connection_pool_kw["ssl_context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIn(
            http.LEGACY_RSA_SUITE,
            {cipher["name"] for cipher in context.get_ciphers()},
        )

    def test_the_suite_list_is_derived_not_hardcoded(self):
        """An interpreter upgrade must be inherited, not overridden.

        The string is built from the live default context, so every suite
        CPython currently ships is present.
        """
        live = [
            cipher["name"]
            for cipher in ssl.create_default_context().get_ciphers()
            if cipher.get("protocol") != "TLSv1.3"
            and not cipher["name"].startswith("TLS_")
        ]
        built = http._compatible_cipher_string().split(":")
        self.assertEqual(built[: len(live)], live)
        self.assertEqual(built[-1], http.LEGACY_RSA_SUITE)


if __name__ == "__main__":
    unittest.main()
