"""Strict, bounded transport for the official Grants.gov extract.

The measured November 2026 server chain omits HydrantID Server CA O1. Supply
that public intermediate only for the two measured origins, while requiring a
complete chain to the ordinary certifi roots and normal hostname verification.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import tempfile
import time
from urllib.parse import urljoin, urlsplit
from zipfile import BadZipFile, ZipFile

import certifi
import requests
from requests.adapters import HTTPAdapter


GRANTS_HOSTS = frozenset({"grants.gov", "www.grants.gov"})
ARCHIVE_CDN_HOST = "prod-grants-gov-chatbot.s3.amazonaws.com"
INTERMEDIATE = Path(__file__).with_name("certificates") / "hydrantid-server-ca-o1.pem"
INTERMEDIATE_SHA256 = "8bb2f6883fed289a521ba27c478482950874e143caccec6fc025990c0c46813e"
MAX_ATTEMPTS = 3
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
FAILURE_PREFIX = "GRANTS_SOURCE_TRANSPORT_FAILURE "


def grants_origin(url):
    """Return the exact supported HTTPS host, or reject the request profile."""
    if not isinstance(url, str) or any(character.isspace() for character in url):
        raise ValueError("Invalid Grants.gov source URL.")
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in GRANTS_HOSTS
                or parsed.port not in (None, 443) or parsed.username or parsed.password):
            raise ValueError("Unsupported Grants.gov source origin.")
    except ValueError:
        raise ValueError("Unsupported Grants.gov source origin.") from None
    return parsed.hostname


def grants_ssl_context():
    pem = INTERMEDIATE.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(pem)
    if hashlib.sha256(der).hexdigest() != INTERMEDIATE_SHA256:
        raise ValueError("Unexpected Grants.gov intermediate certificate.")
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cadata=pem)
    # Python 3.13 enables PARTIAL_CHAIN by default. The supplied intermediate
    # must never become a new trust anchor: the existing root remains required.
    context.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
    return context


def archive_origin(url):
    """The extract index's measured public S3 route uses ordinary TLS roots."""
    try:
        return grants_origin(url)
    except ValueError:
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname == ARCHIVE_CDN_HOST
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
                and re.fullmatch(r"/extracts/GrantsDBExtract\d{8}v2\.zip", parsed.path, re.I)):
            return parsed.hostname
        raise ValueError("Unsupported Grants.gov extract archive origin.") from None


class GrantsIntermediateAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        kwargs["ssl_context"] = grants_ssl_context()
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)

    def send(self, request, **kwargs):
        grants_origin(request.url)
        if kwargs.get("verify", True) is not True or kwargs.get("cert"):
            raise ValueError("Grants.gov source requires ordinary certificate verification.")
        return super().send(request, **kwargs)


def configure_grants_session(session):
    adapter = GrantsIntermediateAdapter()
    for host in GRANTS_HOSTS:
        for port in ("", ":443"):
            session.mount("https://" + host + port + "/", adapter)


def grants_session():
    session = requests.Session()
    session.trust_env = False
    configure_grants_session(session)
    return session


class GrantsSourceTransportError(RuntimeError):
    """A fixed, bounded terminal marker; never response bodies or exception text."""
    def __init__(self, operation, host, kind, attempts):
        self.diagnostics = {
            "version": 1, "operation": operation, "host": host, "kind": kind,
            "attempts": attempts, "certificate_verification": True,
            "source_complete": False, "retry_safe": True,
        }
        super().__init__(FAILURE_PREFIX + json.dumps(
            self.diagnostics, sort_keys=True, separators=(",", ":")))


def _failure_kind(error):
    if isinstance(error, requests.exceptions.SSLError):
        return "tls"
    if isinstance(error, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(error, (requests.exceptions.ConnectionError,
                          requests.exceptions.ChunkedEncodingError)):
        return "connection"
    if isinstance(error, requests.exceptions.HTTPError):
        status = error.response.status_code if error.response is not None else None
        if status == 429 or (status is not None and 500 <= status <= 599):
            return "transient_http"
    return None


def _open_get(session, url, headers, timeout, origin):
    for _ in range(6):
        origin(url)
        response = session.get(url, headers=headers, timeout=timeout, stream=True,
                               allow_redirects=False, verify=True)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise ValueError("Grants.gov redirect has no location.")
        url = urljoin(url, location)
    raise ValueError("Grants.gov redirected too many times.")


def _get_with_retries(session, url, operation, headers, timeout, consume):
    origin = grants_origin if operation == "extract-index" else archive_origin
    host = origin(url)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with _open_get(session, url, headers, timeout, origin) as response:
                response.raise_for_status()
                return consume(response)
        except requests.RequestException as error:
            kind = _failure_kind(error)
            if kind is None:
                raise
            # Certificate failures remain closed immediately. Only transient
            # transport/status failures receive short in-process GET retries.
            if kind == "tls" or attempt == MAX_ATTEMPTS:
                raise GrantsSourceTransportError(operation, host, kind, attempt) from None
            time.sleep(min(2 ** (attempt - 1), 4))


def fetch_extract_index(session, url, headers):
    def read(response):
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > MAX_INDEX_BYTES:
                raise ValueError("Grants.gov extract index exceeded its size limit.")
            chunks.append(chunk)
        return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    return _get_with_retries(session, url, "extract-index", headers, (30, 60), read)


def download_extract_archive(session, url, target, headers):
    target = Path(target)

    def write(response):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent,
                                             prefix=target.name + ".", suffix=".part",
                                             delete=False) as output:
                temporary = Path(output.name)
                size = 0
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise ValueError("Grants.gov extract archive exceeded its size limit.")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            with ZipFile(temporary) as archive:
                if not any(name.lower().endswith(".xml") for name in archive.namelist()):
                    raise BadZipFile("Grants.gov extract archive contained no XML.")
                if archive.testzip() is not None:
                    raise BadZipFile("Grants.gov extract archive failed its CRC check.")
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    _get_with_retries(session, url, "extract-archive", headers, (30, 600), write)
