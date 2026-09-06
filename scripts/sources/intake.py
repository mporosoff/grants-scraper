"""Bounded developer intake through the existing source-adapter lifecycle."""
from __future__ import annotations

from dataclasses import fields
from datetime import date, timedelta
import json
import ipaddress
import math
from pathlib import Path
import re
from urllib.parse import urlparse

from .base import CanonicalOpportunity, SourceAdapter
from .http import PoliteClient
from .registry import REGISTRY, register
from .validate import record_is_publishable

DEFAULT_INPUTS = Path(__file__).resolve().parents[2] / "config/source_intake.json"
MAX_ENTRIES = 20
MAX_MANIFEST_BYTES = 256 * 1024
REQUIRED_FIELDS = {"external_id", "title", "opportunity_number", "url", "agency", "description", "status",
                   "close_date", "posted_date", "award_floor", "award_ceiling", "total_program_funding", "eligibility_text"}
TEXT_FIELDS = {"external_id", "title", "opportunity_number", "url", "agency", "description", "status",
               "close_date", "posted_date", "deadline_note", "eligibility_text", "primary_document_url", "primary_document_name"}
MONEY_FIELDS = {"award_floor", "award_ceiling", "total_program_funding", "expected_number_of_awards"}
LIST_FIELDS = {"applicant_types", "disciplines", "topic_areas", "funding_instruments", "funding_categories"}
SOURCE_TYPES = {"Federal", "State", "Foundation", "International", "Internal", "Other"}
LICENSED_HOSTS = {"pivot.proquest.com", "grantforward.com", "infoedglobal.com", "researchfunding.duke.edu"}


def public_source_url(value, *, resolve=True):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid public source URL")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if (parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password
            or parsed.port not in {None, 80, 443}
            or host.rstrip(".") == "localhost" or host.rstrip(".").endswith(".localhost")
            or (address is not None and (not address.is_global or address.is_multicast))
            or any(host == name or host.endswith("." + name) for name in LICENSED_HOSTS)):
        raise ValueError("source URL is not a permitted public notice")
    if resolve:
        from scripts.extract_document_evidence import validate_public_url
        validate_public_url(value)
    return value


def supported_adapter(slug):
    # A URL is selected from a supported native parser's verified listing.
    # A disabled source or an arbitrary replacement endpoint is never enabled.
    adapter = next((a for a in REGISTRY if a.slug == slug and a.enabled), None)
    if adapter is None or slug not in {"arpa-e", "eere-exchange", "nsf-funding"}:
        raise ValueError("URL intake supports arpa-e, eere-exchange, or nsf-funding; use a cited manifest for unsupported markup")
    return adapter


def preview_url(url, slug, *, client=None, as_of=None):
    adapter = supported_adapter(slug)
    public_source_url(url)
    endpoint = getattr(adapter, "list_url", None) or adapter.feed_url
    expected_host = urlparse(endpoint).hostname
    if urlparse(url).hostname != expected_host:
        raise ValueError("URL does not belong to the selected official source")
    client = client or PoliteClient()
    payload = client.get_text(endpoint)
    parsed = (adapter.parse_html(payload, as_of=as_of) if hasattr(adapter, "parse_html") else adapter.parse(payload))
    matches = [p for p in parsed if p.url == url]
    if len(matches) != 1:
        raise ValueError("official listing does not identify exactly one supported notice at this URL; use a cited manifest")
    record = matches[0].to_record(slug=adapter.slug, source=adapter.display_name, source_type=adapter.source_type)
    ok, reason = record_is_publishable(record, as_of or date.today())
    if not ok:
        raise ValueError("source notice is not publishable: " + reason)
    return {"kind": "url", "adapter": slug, "url": url}, record


def validate_record(entry, *, as_of=None, resolve=False, verify_quotes=False, fetcher=None):
    if not isinstance(entry, dict) or set(entry) != {"kind", "source_name", "source_type", "verified_on", "review_after", "opportunity", "citations"}:
        raise ValueError("invalid record manifest fields")
    if entry["kind"] != "record" or (not isinstance(entry["source_type"], str) or entry["source_type"] not in SOURCE_TYPES):
        raise ValueError("invalid source type")
    if not isinstance(entry["source_name"], str) or not 3 <= len(entry["source_name"]) <= 150 or entry["source_name"] == "Grants.gov":
        raise ValueError("invalid supplemental source name")
    try:
        verified = date.fromisoformat(entry["verified_on"])
        review = date.fromisoformat(entry["review_after"])
    except (ValueError, TypeError):
        raise ValueError("manifest needs explicit ISO verification/review dates") from None
    if not verified <= review <= verified + timedelta(days=30) or verified > (as_of or date.today()):
        raise ValueError("manifest verification is future-dated or exceeds the 30-day review bound")
    data = entry["opportunity"]
    allowed = {f.name for f in fields(CanonicalOpportunity)} - {"extra", "contacts"}
    if not isinstance(data, dict) or not REQUIRED_FIELDS <= set(data) or not set(data) <= allowed:
        raise ValueError("manifest must name required fields explicitly; use null for unknown facts")
    for name, value in data.items():
        if name in TEXT_FIELDS and value is not None and (not isinstance(value, str) or len(value) > 12000):
            raise ValueError("invalid text field: " + name)
        if name in MONEY_FIELDS and value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError("invalid numeric field: " + name)
        if name in LIST_FIELDS and (not isinstance(value, list) or len(value) > 30 or any(not isinstance(v, str) or len(v) > 200 for v in value)):
            raise ValueError("invalid list field: " + name)
    if not isinstance(data["external_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", data["external_id"]):
        raise ValueError("manifest requires a stable official external_id")
    if not isinstance(data["title"], str) or not data["title"].strip() or data["status"] not in {"posted", "forecasted"}:
        raise ValueError("manifest requires a title and explicit supported status")
    for name in ("posted_date", "close_date"):
        if data.get(name) is not None:
            try:
                date.fromisoformat(data[name])
            except (TypeError, ValueError):
                raise ValueError("date must be ISO or null: " + name) from None
    if data.get("cost_share_required") is not None and type(data["cost_share_required"]) is not bool:
        raise ValueError("cost_share_required must be boolean or null")
    if data.get("award_floor") is not None and data.get("award_ceiling") is not None and data["award_floor"] > data["award_ceiling"]:
        raise ValueError("award bounds are contradictory")
    notice_urls = {public_source_url(data["url"], resolve=resolve)}
    if data.get("primary_document_url"):
        notice_urls.add(public_source_url(data["primary_document_url"], resolve=resolve))
    deadlines = data.get("additional_deadlines", [])
    if not isinstance(deadlines, list) or len(deadlines) > 20:
        raise ValueError("invalid additional deadlines")
    for deadline in deadlines:
        if not isinstance(deadline, dict) or not {"kind", "date", "time", "timezone"} <= set(deadline):
            raise ValueError("additional deadlines require explicit kind/date/time/timezone")
        if set(deadline) - {"kind", "date", "time", "timezone", "note", "estimated", "source_url"}:
            raise ValueError("unknown deadline fields")
        date.fromisoformat(deadline["date"])
        if deadline["kind"] not in {"application", "concept_paper", "letter_of_intent", "white_paper", "preapplication", "preproposal"}:
            raise ValueError("unsupported deadline stage")
        if any(deadline.get(k) is not None and (not isinstance(deadline[k], str) or len(deadline[k]) > 500) for k in ("time", "timezone", "note")):
            raise ValueError("invalid deadline details")
        if "estimated" in deadline and type(deadline["estimated"]) is not bool:
            raise ValueError("estimated must be boolean")
        if deadline.get("source_url") and public_source_url(deadline["source_url"], resolve=resolve) not in notice_urls:
            raise ValueError("deadline citation must refer to a supplied official notice")
    citations = entry["citations"]
    if not isinstance(citations, dict) or set(citations) - set(data):
        raise ValueError("invalid manifest citations")
    uncited = {name for name, value in data.items() if value not in (None, [], "")
               and name not in {"external_id", "url", "primary_document_url", "primary_document_name"}} - set(citations)
    if uncited:
        raise ValueError("every supplied fact requires a source citation: " + ", ".join(sorted(uncited)))
    documents = {}
    for citation in citations.values():
        if (not isinstance(citation, dict) or set(citation) != {"url", "quote"}
                or citation["url"] not in notice_urls or not isinstance(citation["quote"], str)
                or not 15 <= len(citation["quote"]) <= 600):
            raise ValueError("citation requires an exact bounded quote and supplied official URL")
        if verify_quotes:
            from scripts.extract_document_evidence import clean_document_text, download_document, extract_containers
            url = citation["url"]
            if url not in documents:
                downloaded = (fetcher or download_document)(url)
                containers, _ = extract_containers(downloaded["content"], downloaded.get("content_type"), None, downloaded.get("url") or url)
                public_source_url(downloaded.get("url") or url, resolve=resolve)
                documents[url] = clean_document_text(" ".join(c.get("text", "") for c in containers))
            if clean_document_text(citation["quote"]) not in documents[url]:
                raise ValueError("manifest quote was not found in the cited official document")
    record_data = dict(data)
    record_data["external_id"] = urlparse(data["url"]).hostname.lower() + ":" + data["external_id"]
    record = CanonicalOpportunity(**record_data).to_record(slug="maintained", source=entry["source_name"], source_type=entry["source_type"])
    record["source_review_after"] = entry["review_after"]
    return record


def load_inputs(path=DEFAULT_INPUTS):
    path = Path(path)
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("intake manifest exceeds its size bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != {"schema_version", "entries"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["entries"], list) or len(value["entries"]) > MAX_ENTRIES):
        raise ValueError("intake requires schema_version 1 and at most 20 entries")
    return value


def entry_key(entry):
    if entry.get("kind") == "url":
        return ("url", entry["adapter"], entry["url"])
    record = validate_record(entry)
    return ("record", record["opportunity_id"])


def accept(entries, path=DEFAULT_INPUTS):
    from .merge import save_source_cache
    current = load_inputs(path) if Path(path).exists() else {"schema_version": 1, "entries": []}
    combined = {entry_key(entry): entry for entry in current["entries"]}
    for entry in entries:
        combined[entry_key(entry)] = entry
    if len(combined) > MAX_ENTRIES:
        raise ValueError("maintained intake is limited to 20 entries")
    current["entries"] = list(combined.values())
    save_source_cache(current, Path(path))


class MaintainedInputs(SourceAdapter):
    slug = "maintained"
    display_name = "Maintained official sources"
    source_type = "Other"
    enabled = True
    min_records = 0
    max_records = MAX_ENTRIES

    def collect(self):
        inputs = load_inputs(self.context.get("intake_path") or DEFAULT_INPUTS)
        as_of = self.context.get("as_of") or date.today()
        records = []
        selectors = []
        for entry in inputs["entries"]:
            if not isinstance(entry, dict):
                raise ValueError("invalid intake entry")
            if entry.get("kind") == "url":
                if set(entry) != {"kind", "adapter", "url"}:
                    raise ValueError("invalid native URL selector")
                supported_adapter(entry["adapter"])
                public_source_url(entry["url"], resolve=False)
                selectors.append({"adapter": entry["adapter"], "url": entry["url"]})
            else:
                records.append(validate_record(entry, as_of=as_of))
        self.diagnostics = {"accepted_records": len(records), "native_url_selectors": selectors}
        return records


register(MaintainedInputs())
