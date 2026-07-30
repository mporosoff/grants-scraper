"""Incrementally monitor official opportunity links.

The checker rotates through the least-recently checked URLs, follows redirects,
and stores only operational metadata. Individual broken links are reported but
do not fail the daily catalog refresh; a large systemic failure can.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import socket
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests

from scripts.build_catalog import USER_AGENT, safe_http_url
from scripts.build_feeds import load_catalog


SCHEMA_VERSION = 1
URL_FIELDS = (
    "primary_document_url",
    "funding_opportunity_url",
    "detail_page",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def catalog_urls(catalog: dict) -> dict[str, list[str]]:
    """Return canonical URL -> sorted record IDs."""
    urls: dict[str, set[str]] = {}
    for record in catalog.get("opportunities") or []:
        record_id = str(
            record.get("opportunity_id")
            or record.get("opportunity_number")
            or record.get("title")
            or ""
        )
        candidates: Iterable = [
            *(record.get(field) for field in URL_FIELDS),
            *(record.get("document_urls") or []),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("url")
            url = safe_http_url(candidate)
            if url:
                urls.setdefault(url, set()).add(record_id)
    return {url: sorted(ids) for url, ids in urls.items()}


def select_urls(
    urls: dict[str, list[str]],
    prior_records: dict,
    limit: int,
) -> list[str]:
    """Prioritize unseen URLs, then the oldest checks."""
    return sorted(
        urls,
        key=lambda url: (
            bool(prior_records.get(url)),
            str(prior_records.get(url, {}).get("checked_at") or ""),
            url,
        ),
    )[: max(0, limit)]


def public_target(url: str) -> tuple[bool, str | None]:
    """Reject local/private targets, including every resolved address."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False, "invalid HTTP URL"
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return False, "local hostname"
    try:
        literal = ipaddress.ip_address(hostname)
        return (literal.is_global, None if literal.is_global else "non-public IP")
    except ValueError:
        pass
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError) as exc:
        return False, f"DNS resolution failed: {str(exc)[:180]}"
    if not addresses or any(not address.is_global for address in addresses):
        return False, "hostname resolves to a non-public IP"
    return True, None


def check_url(url: str, timeout: float = 12.0) -> dict:
    headers = {"User-Agent": USER_AGENT}
    target = url
    redirected = False
    try:
        response = None
        used_get = False
        for _ in range(7):
            allowed, reason = public_target(target)
            if not allowed:
                raise requests.RequestException(
                    f"unsafe or unreachable target: {reason}"
                )
            method = "GET" if used_get else "HEAD"
            request_headers = (
                {**headers, "Range": "bytes=0-1023"}
                if used_get
                else headers
            )
            response = requests.request(
                method,
                target,
                allow_redirects=False,
                timeout=timeout,
                headers=request_headers,
                stream=used_get,
            )
            if response.status_code in {403, 405} and not used_get:
                response.close()
                used_get = True
                continue
            if (
                response.status_code in {301, 302, 303, 307, 308}
                and response.headers.get("location")
            ):
                next_target = safe_http_url(
                    urljoin(target, response.headers["location"])
                )
                response.close()
                if not next_target:
                    raise requests.RequestException(
                        "redirect did not contain a valid HTTP URL"
                    )
                target = next_target
                redirected = True
                used_get = False
                continue
            break
        else:
            raise requests.RequestException("too many redirects")
        if response is None:
            raise requests.RequestException("no HTTP response")
        access_restricted = response.status_code in {401, 403}
        result = {
            "ok": None if access_restricted else 200 <= response.status_code < 400,
            "status": response.status_code,
            "final_url": safe_http_url(target) or url,
            "content_type": (response.headers.get("content-type") or "").split(";", 1)[0],
            "redirected": redirected,
            "access_restricted": access_restricted,
            "checked_at": utc_now(),
            "error": None,
        }
        response.close()
        return result
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": None,
            "final_url": url,
            "content_type": "",
            "redirected": False,
            "access_restricted": False,
            "checked_at": utc_now(),
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


def update_link_state(
    catalog: dict,
    prior: dict,
    *,
    max_checks: int = 150,
    timeout: float = 12.0,
    workers: int = 8,
) -> tuple[dict, list[dict]]:
    urls = catalog_urls(catalog)
    prior_records = prior.get("records") if prior.get("schema_version") == SCHEMA_VERSION else {}
    prior_records = dict(prior_records or {})
    selected = select_urls(urls, prior_records, max_checks)
    checked: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(check_url, url, timeout): url for url in selected}
        for future in as_completed(futures):
            checked[futures[future]] = future.result()

    records = {}
    for url, record_ids in urls.items():
        status = checked.get(url) or prior_records.get(url) or {
            "ok": None,
            "status": None,
            "final_url": url,
            "content_type": "",
            "redirected": False,
            "access_restricted": False,
            "checked_at": None,
            "error": None,
        }
        records[url] = {**status, "record_ids": record_ids}

    results = [{"url": url, **checked[url]} for url in selected]
    state = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "url_count": len(urls),
        "checked_this_run": len(results),
        "healthy_this_run": sum(item["ok"] is True for item in results),
        "broken_this_run": sum(item["ok"] is False for item in results),
        "restricted_this_run": sum(item["ok"] is None for item in results),
        "redirected_this_run": sum(item["redirected"] is True for item in results),
        "records": records,
    }
    return state, results


def serialize_state(state: dict) -> str:
    """Keep generated state valid JSON while limiting it to one line per URL."""
    metadata = {key: value for key, value in state.items() if key != "records"}
    lines = ["{"]
    for key, value in metadata.items():
        lines.append(
            f"  {json.dumps(key)}: "
            f"{json.dumps(value, ensure_ascii=False, separators=(',', ':'))},"
        )
    lines.append('  "records": {')
    records = state.get("records") or {}
    for index, (url, record) in enumerate(records.items()):
        suffix = "," if index < len(records) - 1 else ""
        lines.append(
            f"    {json.dumps(url, ensure_ascii=False)}: "
            f"{json.dumps(record, ensure_ascii=False, separators=(',', ':'))}{suffix}"
        )
    lines.extend(["  }", "}"])
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/opportunities.js")
    parser.add_argument("--state", default="data/link_health.json")
    parser.add_argument("--max-checks", type=int, default=150)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--fail-threshold",
        type=float,
        default=0.35,
        help="Fail if at least 20 checked URLs exceed this broken fraction.",
    )
    args = parser.parse_args(argv)

    catalog = load_catalog(Path(args.catalog))
    state_path = Path(args.state)
    prior = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {}
    )
    state, results = update_link_state(
        catalog,
        prior,
        max_checks=args.max_checks,
        timeout=args.timeout,
        workers=args.workers,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        serialize_state(state),
        encoding="utf-8",
    )
    broken = state["broken_this_run"]
    checked = state["checked_this_run"]
    print(
        f"Checked {checked}/{state['url_count']} links: "
        f"{state['healthy_this_run']} healthy, {broken} broken, "
        f"{state['restricted_this_run']} access-restricted, "
        f"{state['redirected_this_run']} redirected."
    )
    if checked >= 20 and broken / checked > args.fail_threshold:
        print("Systemic link-health threshold exceeded.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
