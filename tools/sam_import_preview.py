"""Preview the staged SAM pilot without writing the catalog or calling providers.

Version 1 uses one listing and at most two explicitly selected descriptions.
Version 2 uses two anonymous public reads per reviewed notice, reusing snapshots
in the real merge. No catalog or cache writes occur in either mode.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote

from scripts.solicitation_identity import normalized_number
from scripts.sources.sam_api import SamError, fetch_description, fetch_listing, redacted
from scripts.sources.sam_public import fetch_notice
from scripts.sources.sam_reviewed import make_record
from scripts.sources.adapters.sam_gov import SamGovAdapter, discovery_candidates, load_config
from scripts.sources.merge import integrate, load_catalog

ROOT = Path(__file__).resolve().parents[1]
NOTICE_ID = re.compile(r'[0-9a-f]{32}')
SAM_LINK = re.compile(r'^https://sam\.gov/(?:workspace/contract/)?opp/([0-9a-f]{32})/view/?$')
EXCERPT_TERMS = re.compile(r'universit|academic|higher education|eligib|proposal|white paper|research|submission', re.I)


def context_allowed(environment):
    return environment.get('GITHUB_ACTIONS') != 'true' or all(environment.get(name) == value for name, value in {
        'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_REF': 'refs/heads/main',
        'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
        'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/sam-import-preview.yml@refs/heads/main',
    }.items())


def description_ids(value):
    values = [part.strip().lower() for part in value.split(',') if part.strip()]
    if len(values) > 2 or len(values) != len(set(values)) or any(not NOTICE_ID.fullmatch(item) for item in values):
        raise ValueError('Select at most two distinct 32-character notice IDs')
    return values


def excerpts(text, *, api_key=''):
    """Retain disjoint, contact-scrubbed samples totaling at most half the text."""
    # The transport already strips HTML. Normalize encoded contact routes too,
    # before choosing windows, so truncation cannot expose part of an address.
    text = redacted(unquote(unescape(text)), api_key)
    text = re.sub(r'<[^>]*>', ' ', text)
    text = re.sub(r'\b(?:mailto|tel|sms|callto)\s*:\s*[^\s<>"\x27]+',
                  '[contact omitted]', text, flags=re.I)
    text = re.sub(r'[a-z0-9.!#$%&*+/=?^_\x60{|}~\x27-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+',
                  '[contact omitted]', text, flags=re.I)
    text = re.sub(
        r'(?<!\w)(?:\+\d(?:[ .()-]*\d){6,14}|'
        r'(?:1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}|\d{3}[ .-]\d{4})'
        r'(?:\s*(?:ext(?:ension)?\.?|x)\s*\d{1,6})?(?!\w)',
        '[contact omitted]', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) < 1000:
        return []
    budget = min(2000, len(text) // 2)
    selected, previous_end, used = [], -40, 0
    for match in EXCERPT_TERMS.finditer(text):
        start = max(0, match.start() - 100)
        if start < previous_end + 40:
            continue
        end = min(len(text), match.end() + 300, start + 400, start + budget - used)
        if end <= match.end():
            break
        selected.append(text[start:end])
        used += end - start
        previous_end = end
        if len(selected) == 5 or used == budget:
            break
    return selected


def existing_matches(row, records):
    same_notice, same_number = [], []
    number = normalized_number(row.get('solicitationNumber'))
    for record in records:
        identity = {'opportunity_id': record.get('opportunity_id'), 'source': record.get('source'),
                    'agency': record.get('agency'), 'opportunity_number': record.get('opportunity_number')}
        links = [record.get(name) for name in ('detail_page', 'funding_opportunity_url', 'primary_document_url')]
        if any((match := SAM_LINK.fullmatch(str(link or ''))) and match[1] == row.get('noticeId') for link in links):
            same_notice.append(identity)
        if number and normalized_number(record.get('opportunity_number')) == number:
            same_number.append(identity)
    return {'same_sam_notice': same_notice, 'same_number_requires_sponsor_check': same_number}


def merge_preview(adapter, catalog_path, cache_path, today):
    # Disable unrelated public identity enrichment; this preview owns only the
    # explicitly selected SAM request inventory.
    old_enrich = os.environ.get('VPR_ENRICH_LINKS')
    os.environ['VPR_ENRICH_LINKS'] = 'false'
    try:
        return integrate(catalog_path=catalog_path, cache_path=cache_path, adapters=[adapter],
                         include_disabled=True, write=False, as_of=today)
    finally:
        if old_enrich is None:
            os.environ.pop('VPR_ENRICH_LINKS', None)
        else:
            os.environ['VPR_ENRICH_LINKS'] = old_enrich


def reviewed_preview(config, *, root, today, public_notice):
    """Fetch the bounded approved inventory once; never read credentials."""
    def fetch(approval):
        try:
            notice, detail = public_notice(approval['notice_id'])
            return notice, detail, False
        except SamError as error:
            return None, error.diagnostics, True

    approvals = config['approved_notices']
    with ThreadPoolExecutor(max_workers=4) as executor:
        fetched = list(executor.map(fetch, approvals))
    request_count = sum(detail.get('request_count', 0) for _, detail, _ in fetched)
    failures = [{'notice_id': approval['notice_id'], 'http_status': detail.get('http_status')}
                for approval, (_, detail, failed) in zip(approvals, fetched) if failed]
    if failures:
        raise SamError('reviewed_notice_fetch_failed', {
            'request_count': request_count, 'outcome': 'public_notice_unavailable',
            'failures': failures})
    snapshots = {approval['notice_id']: (notice, detail)
                 for approval, (notice, detail, _) in zip(approvals, fetched)}
    catalog_path = root / 'data/opportunities.js'
    cache_path = root / 'data/source_records.json'
    records = load_catalog(catalog_path).get('opportunities', [])
    candidates = []
    for approval in approvals:
        notice, _ = snapshots[approval['notice_id']]
        _, reasons = make_record(notice, approval, today)
        row = {'noticeId': notice['notice_id'], 'solicitationNumber': notice['solicitation_number']}
        candidates.append(dict(notice, catalog_matches=existing_matches(row, records),
                               admission_reasons=reasons))
    # The real adapter must consume the exact snapshots just inspected. A
    # missing/unapproved ID fails locally rather than making a surprise request.
    adapter = SamGovAdapter(config_path=root / 'config/sam_gov.json',
                            reviewed_client=lambda notice_id: snapshots[notice_id])
    summary = merge_preview(adapter, catalog_path, cache_path, today)
    return {'schema_version': 2, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'outcome': 'preview_completed', 'request_count': request_count,
            'request_mode': 'anonymous_public_reviewed_notices', 'credentialed_requests': 0,
            'production_enabled': config['enabled'], 'approved_notices': len(approvals),
            'catalog_changed': False, 'candidates': candidates,
            'comparison_scope': 'Current catalog only; absence here does not establish absence from Grants.gov',
            'description_inspections': [], 'reviewed_notices_match': all(
                not row['admission_reasons'] for row in candidates),
            'merge_preview': summary,
            'readiness': 'Exact reviewed notices and application stages checked against current public snapshots'}


def preview(api_key=None, selected_ids=(), *, root=ROOT, today=None, listing=fetch_listing,
            description=fetch_description, public_notice=fetch_notice):
    today = today or datetime.now(timezone.utc).date()
    if len(selected_ids) > 2 or len(set(selected_ids)) != len(selected_ids) or any(not NOTICE_ID.fullmatch(i) for i in selected_ids):
        raise ValueError('Select at most two distinct notice IDs')
    root = Path(root)
    config_path = root / 'config/sam_gov.json'
    config = load_config(config_path)
    if config.get('schema_version') == 2:
        if selected_ids:
            raise ValueError('Reviewed public previews do not fetch legacy descriptions')
        return reviewed_preview(config, root=root, today=today, public_notice=public_notice)
    api_key = os.environ.get('SAM_API_KEY', '') if api_key is None else api_key
    rows, diagnostics = listing(api_key, today=today)
    catalog_path = root / 'data/opportunities.js'
    cache_path = root / 'data/source_records.json'
    catalog = load_catalog(catalog_path)
    records = catalog.get('opportunities', [])
    candidates = []
    for row in rows:
        candidates.append({key: value for key, value in row.items() if key != 'description_route'} |
                          {'catalog_matches': existing_matches(row, records)})
    inspections = []
    request_count = diagnostics.get('request_count', 1)
    for notice_id in selected_ids:
        row = next((row for row in rows if row.get('noticeId') == notice_id), None)
        inspection = {'notice_id': notice_id, 'source_url': f'https://sam.gov/opp/{notice_id}/view',
                      'eligibility_verified': False, 'status': 'not_in_listing', 'excerpts': []}
        if row and row.get('description_route'):
            # One attempt only; even an HTTP/network failure consumes this slot.
            request_count += 1
            try:
                text, detail = description(api_key, notice_id, route=row['description_route'])
                text = redacted(text, api_key.strip())
                inspection.update(status='review_required', excerpts=excerpts(text, api_key=api_key.strip()),
                                  text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                  transport=detail)
            except SamError as error:
                inspection.update(status='description_unavailable', transport=error.diagnostics)
        elif row:
            inspection['status'] = 'no_verified_description_route'
        inspections.append(inspection)
    # Reuse the single listing in the real canonical merge preview. Disable
    # unrelated public identity enrichment, which otherwise has its own budget.
    adapter = SamGovAdapter(config_path=config_path, client=lambda *_args, **_kwargs: (rows, diagnostics))
    summary = merge_preview(adapter, catalog_path, cache_path, today)
    report = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'outcome': 'preview_completed', 'request_count': request_count,
              'production_enabled': config['enabled'], 'approved_notices': len(config['approved_notices']),
              'catalog_changed': False, 'listing': diagnostics, 'candidates': candidates,
              'comparison_scope': 'Current catalog only; absence here does not establish absence from Grants.gov',
              'prefilter': discovery_candidates(rows, today), 'description_inspections': inspections,
              'merge_preview': summary,
              'readiness': 'Requires reviewed academic eligibility, actionable submission terms, and sponsor/number duplicate checks before activation'}
    return redacted(report, api_key.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--description-notice-ids', default='')
    args = parser.parse_args()
    try:
        if not context_allowed(os.environ):
            raise ValueError('Manual main workflow required')
        selected = description_ids(args.description_notice_ids)
        report = preview(None, selected)
        passed = report['merge_preview']['validation']['ok'] and all(
            source['status'] == 'refreshed' for source in report['merge_preview']['sources']) and report.get('reviewed_notices_match', True)
    except SamError as error:
        report = {'schema_version': 1, 'outcome': 'preview_failed', 'catalog_changed': False,
                  'listing': error.diagnostics, 'request_count': error.diagnostics.get('request_count', 0)}
        passed = False
    except (ValueError, OSError, KeyError, TypeError):
        # Neither exceptions nor raw API bodies belong in Actions logs/artifacts.
        report = {'schema_version': 1, 'outcome': 'preview_failed', 'catalog_changed': False}
        passed = False
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
    print(json.dumps({'outcome': report['outcome'], 'request_count': report.get('request_count'),
                      'catalog_changed': False}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
