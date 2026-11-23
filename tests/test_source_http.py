from io import BytesIO
import hashlib
import json
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from zipfile import BadZipFile, ZipFile

import requests

from scripts import build_catalog, document_acquisition, source_http as http
from tools import release_dependencies


INDEX = "https://www.grants.gov/xml-extract"
ARCHIVE = ("https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/"
           "GrantsDBExtract20261123v2.zip")
PAGE = '<a href="' + ARCHIVE + '">Latest enhanced extract</a>'


def zip_bytes():
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("GrantsDBExtract20261123v2.xml", "<Grants/>")
    return output.getvalue()


def response(body=b"", *, status=200, chunks=None, location=None):
    result = Mock(status_code=status, encoding="utf-8", headers={})
    if location:
        result.headers["Location"] = location
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(side_effect=lambda *_: (result.close(), False)[1])
    result.iter_content.side_effect = lambda **_: iter(chunks if chunks is not None else [body])
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError("bounded fixture", response=result)
    return result


class GrantsSourceTransport(unittest.TestCase):
    def test_intermediate_profile_keeps_full_root_and_hostname_verification(self):
        context = http.grants_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN, 0)
        certificates = {hashlib.sha256(cert).hexdigest() for cert in context.get_ca_certs(binary_form=True)}
        self.assertIn(http.INTERMEDIATE_SHA256, certificates)
        self.assertIn("5d56499be4d2e08bcfcad08a3e38723d50503bde706948e42f55603019e528ae", certificates)
        with requests.Session() as session:
            default = session.get_adapter(ARCHIVE)
            document_acquisition.configure_session(session)
            for host in http.GRANTS_HOSTS:
                for port in ("", ":443"):
                    self.assertIsInstance(session.get_adapter("https://" + host + port + "/notice"),
                                          http.GrantsIntermediateAdapter)
                for url in ("http://" + host + "/", "https://" + host + ":444/",
                            "https://" + host + ".evil.test/"):
                    self.assertNotIsInstance(session.get_adapter(url), http.GrantsIntermediateAdapter)
            self.assertIs(session.get_adapter(ARCHIVE), default)
            self.assertNotIsInstance(session.get_adapter("https://nspires.nasaprs.com/"),
                                     http.GrantsIntermediateAdapter)
        with http.grants_session() as session:
            self.assertFalse(session.trust_env)
            adapter = session.get_adapter(INDEX)
            request = requests.Request("GET", INDEX).prepare()
            pool = adapter.get_connection_with_tls_context(request, True, proxies={})
            selected = pool.conn_kw["ssl_context"]
            self.assertIs(selected, adapter.poolmanager.connection_pool_kw["ssl_context"])
            self.assertEqual(selected.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(selected.check_hostname)
            self.assertEqual(selected.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN, 0)
            with self.assertRaises(ValueError):
                adapter.send(request, verify=False)
            with self.assertRaises(ValueError):
                adapter.send(request, verify="custom-roots.pem")
        with patch.object(http, "INTERMEDIATE_SHA256", "0" * 64), self.assertRaises(ValueError):
            http.grants_ssl_context()

    def test_downloader_retries_index_and_restarts_interrupted_zip_atomically(self):
        good = zip_bytes()
        def broken(**_):
            yield good[:20]
            raise requests.exceptions.ChunkedEncodingError("secret body not retained")
        partial = response()
        partial.iter_content.side_effect = broken
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.side_effect = [requests.Timeout("private body"), response(PAGE.encode()),
                                   partial, response(good)]
        with TemporaryDirectory() as directory, patch.object(build_catalog, "grants_session", return_value=session), \
                patch.object(http.time, "sleep") as sleep:
            target = Path(directory) / "extract.zip"
            target.write_bytes(b"previous complete target")
            self.assertEqual(build_catalog.download_latest_extract(target), ARCHIVE)
            self.assertEqual(target.read_bytes(), good)
            self.assertEqual(list(Path(directory).glob("*.part")), [])
            self.assertEqual(sleep.call_count, 2)
        self.assertEqual(session.get.call_count, 4)
        for call in session.get.call_args_list:
            self.assertTrue(call.kwargs["verify"])
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertTrue(call.kwargs["stream"])
        partial.close.assert_called_once()

    def test_retry_exhaustion_emits_only_safe_terminal_marker_and_keeps_target(self):
        for operation, url in (("extract-index", INDEX), ("extract-archive", ARCHIVE)):
            for status in (429, 503):
                with self.subTest(operation=operation, status=status), TemporaryDirectory() as directory:
                    target = Path(directory) / "extract.zip"
                    target.write_bytes(b"previous")
                    session = Mock()
                    session.get.side_effect = [response(status=status) for _ in range(http.MAX_ATTEMPTS)]
                    with patch.object(http.time, "sleep"), self.assertRaises(http.GrantsSourceTransportError) as raised:
                        if operation == "extract-index":
                            http.fetch_extract_index(session, url, {})
                        else:
                            http.download_extract_archive(session, url, target, {})
                    marker = str(raised.exception)
                    self.assertTrue(marker.startswith(http.FAILURE_PREFIX))
                    payload = json.loads(marker.removeprefix(http.FAILURE_PREFIX))
                    self.assertEqual(payload, {"version": 1, "operation": operation,
                        "host": http.ARCHIVE_CDN_HOST if operation == "extract-archive" else "www.grants.gov",
                        "kind": "transient_http", "attempts": 3, "certificate_verification": True,
                        "source_complete": False, "retry_safe": True})
                    self.assertEqual(target.read_bytes(), b"previous")
                    self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_tls_failure_fails_closed_and_invalid_content_or_denial_is_not_retry_admitted(self):
        session = Mock()
        session.get.side_effect = requests.exceptions.SSLError("private certificate diagnostics")
        with patch.object(http.time, "sleep") as sleep, self.assertRaises(http.GrantsSourceTransportError) as raised:
            http.fetch_extract_index(session, INDEX, {})
        self.assertEqual(raised.exception.diagnostics["kind"], "tls")
        self.assertEqual(raised.exception.diagnostics["attempts"], 1)
        self.assertNotIn("private", str(raised.exception))
        sleep.assert_not_called()
        for status in (403, 404):
            session = Mock()
            session.get.return_value = response(status=status)
            with self.assertRaises(requests.HTTPError):
                http.fetch_extract_index(session, INDEX, {})
            self.assertEqual(session.get.call_count, 1)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "extract.zip"
            session = Mock()
            session.get.return_value = response(b"<html>upstream error</html>")
            with self.assertRaises(BadZipFile):
                http.download_extract_archive(session, ARCHIVE, target, {})
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(session.get.call_count, 1)

    def test_redirects_retain_exact_source_scope_and_default_cdn_tls(self):
        session = Mock()
        session.get.side_effect = [response(status=302, location="https://grants.gov/xml-extract"),
                                   response(PAGE.encode())]
        self.assertEqual(http.fetch_extract_index(session, INDEX, {}), PAGE)
        self.assertEqual(session.get.call_count, 2)
        for destination in ("http://www.grants.gov/xml-extract", "https://www.grants.gov:444/a",
                            "https://www.grants.gov.evil.test/a", "https://127.0.0.1/a"):
            session = Mock()
            redirect = response(status=302, location=destination)
            session.get.return_value = redirect
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                http.fetch_extract_index(session, INDEX, {})
            self.assertEqual(session.get.call_count, 1)
            redirect.close.assert_called_once()
        for url in ("https://" + http.ARCHIVE_CDN_HOST + "/other.zip",
                    ARCHIVE + "?private=1", ARCHIVE.replace("https:", "http:")):
            with self.assertRaises(ValueError):
                http.archive_origin(url)

    def test_document_profile_applies_to_direct_and_redirected_grants_hops(self):
        from scripts import extract_document_evidence as documents
        for start in (INDEX, "https://agency.example/notice"):
            visited = []
            with requests.Session() as session:
                session.trust_env = False
                def get(url, **kwargs):
                    visited.append((url, session.get_adapter(url), kwargs))
                    if url != INDEX:
                        return response(status=302, location=INDEX)
                    return response(b"<html>official notice</html>")
                with patch.object(session, "get", side_effect=get), \
                        patch.object(documents, "validate_public_url", side_effect=lambda url: url):
                    result = documents.download_document(start, {"Authorization": "secret", "Cookie": "secret"},
                                                         session=session)
            self.assertEqual(result["content"], b"<html>official notice</html>")
            self.assertIsInstance(visited[-1][1], http.GrantsIntermediateAdapter)
            for url, adapter, kwargs in visited:
                self.assertFalse(kwargs["allow_redirects"])
                self.assertNotIn("Authorization", kwargs["headers"])
                self.assertNotIn("Cookie", kwargs["headers"])
                if url != INDEX:
                    self.assertNotIsInstance(adapter, http.GrantsIntermediateAdapter)

    def test_certificate_bytes_are_a_source_generation_dependency(self):
        root = Path(__file__).resolve().parents[1]
        policy = json.loads((root / "config/release_dependencies.json").read_text(encoding="utf-8"))
        name = "scripts/certificates/hydrantid-server-ca-o1.pem"
        self.assertIn(name, policy["generation"])
        self.assertIn(name, policy["dependency_groups"]["source"]["patterns"])
        first = release_dependencies.semantic_bytes(name, (root / name).read_bytes())
        second = release_dependencies.semantic_bytes(name, (root / name).read_bytes() + b"changed")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
