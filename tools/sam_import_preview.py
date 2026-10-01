"""Preview the staged SAM pilot without writing the catalog or calling providers.

One listing request and at most two explicitly selected description requests.
Descriptions remain ephemeral; only short review excerpts enter the report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from scripts.solicitation_identity import normalized_number
from scripts.sources.sam_api import SamError, fetch_description, fetch_listing
from scripts.sources.adapters.sam_gov import SamGovAdapter, discovery_candidates, load_config
from scripts.sources.merge import integrate, load_catalog
from tools.sam_access_probe import redacted

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


def excerpts(text):
    """Keep bounded review quotations, never the complete description."""
    text = re.sub(r'\s+', ' ', text).strip()
    selected, end = [], -1
    for match in EXCERPT_TERMS.finditer(text):
        if match.start() < end:
            continue
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 300)
        selected.append(text[start:end])
        if len(selected) == 5:
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


def preview(api_key, selected_ids=(), *, root=ROOT, today=None, listing=fetch_listing, description=fetch_description):
    today = today or datetime.now(timezone.utc).date()
    if len(selected_ids) > 2 or len(set(selected_ids)) != len(selected_ids) or any(not NOTICE_ID.fullmatch(i) for i in selected_ids):
        raise ValueError('Select at most two distinct notice IDs')
    root = Path(root)
    config_path = root / 'config/sam_gov.json'
    config = load_config(config_path)
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
                inspection.update(status='review_required', excerpts=excerpts(text),
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
    old_enrich = os.environ.get('VPR_ENRICH_LINKS')
    os.environ['VPR_ENRICH_LINKS'] = 'false'
    try:
        summary = integrate(catalog_path=catalog_path, cache_path=cache_path, adapters=[adapter],
                            include_disabled=True, write=False, as_of=today)
    finally:
        if old_enrich is None:
            os.environ.pop('VPR_ENRICH_LINKS', None)
        else:
            os.environ['VPR_ENRICH_LINKS'] = old_enrich
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
        report = preview(os.environ.get('SAM_API_KEY', ''), selected)
        passed = report['merge_preview']['validation']['ok'] and all(
            source['status'] == 'refreshed' for source in report['merge_preview']['sources'])
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
