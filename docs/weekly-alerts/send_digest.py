"""Weekly email-digest engine for Funding Finder saved searches.

This runs from a PRIVATE companion repository (so subscriber email addresses are
never stored in the public site repo). Once a week a GitHub Action:
  1. clones the public site repo (public -> no auth) to get the current catalog
     and the shared matcher (``scripts/alert_match.py``);
  2. runs this script, which -- for each active subscription -- reruns the saved
     search, selects unseen new opportunities and relevant deadline/amendment/
     closure events since that subscriber's last email, and sends a digest by
     SMTP;
  3. commits the updated ``state.json`` (last-run watermark) back to the private
     repo.

Because it reuses the site's exact tokenizer + prebuilt BM25 index, a saved
search ranks in the email the same way it does on the website.

Standard library only. Configuration comes from environment variables (set as
GitHub Actions secrets):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM

Run:
    python send_digest.py --site ./site --subscriptions subscriptions.json \
        --state state.json --send
Use --dry-run to preview without sending or changing state.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

DEFAULT_WINDOW_DAYS = 7
MAX_ITEMS_PER_EMAIL = 25
MAX_REMEMBERED_IDS = 500
SITE_URL = "https://mporosoff.github.io/grants-scraper/match_explorer.html"
FEEDS_URL = "https://mporosoff.github.io/grants-scraper/feeds/index.html"


# --------------------------------------------------------------------------- #
# Shared logic is imported from the cloned public repo (single source of truth)
# --------------------------------------------------------------------------- #
def _import_shared(site_dir: Path):
    sys.path.insert(0, str(site_dir))
    from scripts.alert_match import is_new_since, load_catalog, search_catalog  # noqa: E402
    from scripts.build_feeds import best_url  # noqa: E402

    return load_catalog, search_catalog, is_new_since, best_url


def record_id(record: dict) -> str:
    return str(record.get("opportunity_id") or record.get("opportunity_number") or record.get("title"))


def select_new(ranked: list[dict], since, seen: set, is_new_since, limit: int = MAX_ITEMS_PER_EMAIL) -> list[dict]:
    """Keep ranked records that are new since ``since`` and not already notified."""
    fresh = []
    for record in ranked:
        if record_id(record) in seen:
            continue
        if is_new_since(record, since):
            fresh.append(record)
        if len(fresh) >= limit:
            break
    return fresh


def load_change_events(site_dir: Path) -> list[dict]:
    path = site_dir / "feeds" / "changes.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("events") or []
    except (OSError, json.JSONDecodeError):
        return []


def select_updates(
    events: list[dict],
    ranked: list[dict],
    seen_ids: set,
    notified_event_ids: set,
    since: date,
    limit: int = MAX_ITEMS_PER_EMAIL,
) -> list[dict]:
    """Select relevant deadline/amendment/closure events for a subscription."""
    matched_ids = {record_id(record) for record in ranked}
    selected = []
    for event in events:
        if event.get("type") == "new" or event.get("id") in notified_event_ids:
            continue
        try:
            changed = date.fromisoformat(str(event.get("changed_at") or "")[:10])
        except ValueError:
            continue
        if changed < since:
            continue
        opportunity_id = str(event.get("opportunity_id") or "")
        relevant = opportunity_id in matched_ids
        if event.get("type") == "closed_or_removed":
            relevant = opportunity_id in seen_ids
        if relevant:
            selected.append(event)
        if len(selected) >= limit:
            break
    return selected


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    head = (name[:2] + "…") if len(name) > 2 else "…"
    return f"{head}@{domain}"


def subscription_is_active(sub: dict) -> bool:
    """Require both an active subscription and explicit recorded consent."""
    return sub.get("active", True) and sub.get("confirmed") is True


# --------------------------------------------------------------------------- #
# Email rendering
# --------------------------------------------------------------------------- #
def _describe_search(sub: dict) -> str:
    parts = []
    if sub.get("query"):
        parts.append(f'“{sub["query"]}”')
    filters = sub.get("filters") or {}
    for facet, values in filters.items():
        if values:
            parts.append(f"{facet}: {', '.join(values)}")
    return " · ".join(parts) or "all new opportunities"


def render_text(sub: dict, items: list[dict], best_url, updates: list[dict] | None = None) -> str:
    updates = updates or []
    lines = [
        f"Funding alerts for your saved search ({_describe_search(sub)}):",
        "",
    ]
    if items:
        lines.extend(["NEW MATCHES", ""])
        for record in items:
            lines.append(f"• {record.get('title') or 'Untitled opportunity'}")
            meta = []
            if record.get("agency"):
                meta.append(str(record["agency"]))
            if record.get("close_date"):
                meta.append(f"closes {record['close_date']}")
            if record.get("source"):
                meta.append(str(record["source"]))
            if meta:
                lines.append(f"  {' · '.join(meta)}")
            lines.append(f"  {best_url(record)}")
            lines.append("")
    if updates:
        lines.extend(["CHANGES TO MATCHES YOU FOLLOW", ""])
        for event in updates:
            record = event.get("record") or {}
            lines.append(
                f"• {event.get('label') or 'Opportunity update'}: "
                f"{record.get('title') or 'Untitled opportunity'}"
            )
            if event.get("detail"):
                lines.append(f"  {event['detail']}")
            lines.append(f"  {best_url(record)}")
            lines.append("")
    lines += [
        "—",
        f"Search Funding Finder: {SITE_URL}",
        f"Subscribe by RSS instead: {FEEDS_URL}",
        "",
        "To stop these emails or change your saved search, reply to this message.",
        "Always confirm details on the official notice before acting.",
    ]
    return "\n".join(lines)


def render_html(sub: dict, items: list[dict], best_url, updates: list[dict] | None = None) -> str:
    from html import escape

    updates = updates or []
    rows = []
    for record in items:
        meta = []
        if record.get("agency"):
            meta.append(escape(str(record["agency"])))
        if record.get("close_date"):
            meta.append(f"closes {escape(str(record['close_date']))}")
        if record.get("source"):
            meta.append(escape(str(record["source"])))
        summary = escape((record.get("description") or "")[:240])
        rows.append(
            f'<li style="margin:0 0 14px">'
            f'<a href="{escape(best_url(record))}" style="font-weight:600;color:#12467d;text-decoration:none">'
            f'{escape(record.get("title") or "Untitled opportunity")}</a><br>'
            f'<span style="color:#556;font-size:13px">{" · ".join(meta)}</span><br>'
            f'<span style="color:#333;font-size:13px">{summary}</span></li>'
        )
    update_rows = []
    for event in updates:
        record = event.get("record") or {}
        update_rows.append(
            f'<li style="margin:0 0 14px">'
            f'<strong>{escape(event.get("label") or "Opportunity update")}:</strong> '
            f'<a href="{escape(best_url(record))}" style="font-weight:600;color:#12467d;text-decoration:none">'
            f'{escape(record.get("title") or "Untitled opportunity")}</a><br>'
            f'<span style="color:#556;font-size:13px">{escape(event.get("detail") or "")}</span></li>'
        )
    return f"""<!doctype html><html><body style="font-family:system-ui,Arial,sans-serif;color:#222;max-width:640px;margin:0 auto">
  <h2 style="font-size:18px">Funding alerts for your saved search</h2>
  <p style="color:#556;font-size:13px">{escape(_describe_search(sub))}</p>
  {f'<h3 style="font-size:15px">New matches</h3><ul style="list-style:none;padding:0">{"".join(rows)}</ul>' if rows else ''}
  {f'<h3 style="font-size:15px">Changes to matches you follow</h3><ul style="list-style:none;padding:0">{"".join(update_rows)}</ul>' if update_rows else ''}
  <hr style="border:none;border-top:1px solid #ddd">
  <p style="font-size:12px;color:#667">
    <a href="{SITE_URL}">Search Funding Finder</a> ·
    <a href="{FEEDS_URL}">Subscribe by RSS</a><br>
    To stop these emails or change your saved search, just reply.
    Always confirm details on the official notice before acting.
  </p>
</body></html>"""


# --------------------------------------------------------------------------- #
# SMTP
# --------------------------------------------------------------------------- #
def send_email(to_email: str, subject: str, text_body: str, html_body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", user)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(("Funding Finder", from_addr))
    message["To"] = to_email
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        if smtp.has_extn("starttls"):
            smtp.starttls()
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run(args) -> int:
    site_dir = Path(args.site)
    load_catalog, search_catalog, is_new_since, best_url = _import_shared(site_dir)

    catalog = load_catalog(Path(args.catalog) if args.catalog else site_dir / "data/opportunities.js")
    change_events = load_change_events(site_dir)
    subscriptions = json.loads(Path(args.subscriptions).read_text(encoding="utf-8"))
    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    today = datetime.now(timezone.utc).date()
    fallback_since = date.fromordinal(today.toordinal() - args.window_days)

    sent = 0
    for sub in subscriptions:
        # Consent is fail-closed: a missing flag never authorizes email.
        if not subscription_is_active(sub):
            continue
        sub_id = str(sub["id"])
        prior = state.get(sub_id, {})
        seen = set(prior.get("notified_ids", []))
        notified_event_ids = set(prior.get("notified_event_ids", []))
        try:
            last_run = date.fromisoformat(prior["last_run"])
        except (KeyError, ValueError):
            last_run = fallback_since
        since = max(last_run, fallback_since) if prior.get("last_run") else fallback_since

        # Apply the date/seen gate before the final per-email cap so a broad
        # query cannot hide new matches behind hundreds of older high scorers.
        ranked = search_catalog(
            catalog,
            sub.get("query", ""),
            sub.get("filters"),
            as_of=today,
        )
        fresh = select_new(ranked, since, seen, is_new_since)
        updates = select_updates(
            change_events,
            ranked,
            seen,
            notified_event_ids,
            since,
        )
        fresh_ids = {record_id(record) for record in fresh}
        updates = [
            event
            for event in updates
            if str(event.get("opportunity_id") or "") not in fresh_ids
        ]

        if not fresh and not updates:
            print(f"[{sub_id}] no new matches or changes for {_mask(sub['email'])}")
            continue

        subject = (
            f"Funding Finder: {len(fresh)} new, {len(updates)} changed "
            "for your saved search"
        )
        if args.dry_run:
            print(
                f"[{sub_id}] DRY RUN -> {_mask(sub['email'])}: "
                f"{len(fresh)} new, {len(updates)} changed"
            )
            for record in fresh[:5]:
                print(f"        - {record.get('title')}")
            continue

        send_email(
            sub["email"],
            subject,
            render_text(sub, fresh, best_url, updates),
            render_html(sub, fresh, best_url, updates),
        )
        sent += 1
        print(f"[{sub_id}] sent {len(fresh)} items to {_mask(sub['email'])}")

        remembered = list(dict.fromkeys(
            [*prior.get("notified_ids", []), *(record_id(record) for record in fresh)]
        ))
        remembered_events = list(dict.fromkeys(
            [*prior.get("notified_event_ids", []), *(event["id"] for event in updates)]
        ))
        state[sub_id] = {
            "last_run": today.isoformat(),
            "notified_ids": remembered[-MAX_REMEMBERED_IDS:],
            "notified_event_ids": remembered_events[-MAX_REMEMBERED_IDS:],
        }
        # Persist after each successful send. If a later subscriber fails, the
        # workflow's always-run commit step can still retain this watermark.
        state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if not args.dry_run:
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Done. Sent {sent} digest email(s).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Send weekly Funding Finder digests.")
    parser.add_argument("--site", default="./site", help="Path to a checkout of the public site repo.")
    parser.add_argument("--catalog", default="", help="Override catalog path (defaults to <site>/data/opportunities.js).")
    parser.add_argument("--subscriptions", default="subscriptions.json")
    parser.add_argument("--state", default="state.json")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--send", dest="dry_run", action="store_false")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.set_defaults(dry_run=True)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
