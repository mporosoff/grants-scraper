"""Official routes retained from identity-proven duplicate source records.

These are retrieval candidates, not accepted scientific or administrative
facts. Existing bounded fetch, redirect, scope, and evidence gates still run.
"""
from copy import deepcopy


def permitted_url(value):
    from scripts.sources.intake import public_source_url
    try:
        return public_source_url(value, resolve=False)
    except (TypeError, ValueError):
        return None


def document_candidates(record):
    candidates = []
    designated = record.get('primary_document_url')
    if designated:
        candidates.append({'url': designated, 'name': record.get('primary_document_name'), 'role': 'primary_notice'})
    agency_notice = record.get('funding_opportunity_url') or (record.get('detail_page')
        if record.get('source') and record.get('source') != 'Grants.gov' else None)
    if agency_notice and agency_notice != designated:
        candidates.append({'url': agency_notice, 'name': None, 'role': 'agency_notice'})
    for value in record.get('document_urls') or []:
        if isinstance(value, str):
            candidates.append({'url': value, 'name': None, 'role': 'attachment_candidate'})
        elif isinstance(value, dict):
            candidates.append({'url': value.get('url') or value.get('download_url'),
                               'name': value.get('name') or value.get('file_name'), 'role': 'attachment_candidate'})
    candidates.extend(deepcopy(record.get('official_document_candidates') or []))
    seen, output = set(), []
    for candidate in candidates:
        url = permitted_url(candidate.get('url'))
        if not url or url in seen:
            continue
        # Ordinary catalog document fields originate in supported official
        # sources. Retained supplemental metadata never bypasses URL guards.
        seen.add(url)
        output.append({key: candidate.get(key) for key in ('url', 'name', 'role', 'source', 'source_opportunity_id')})
    return output[:20]


def merge_duplicate_evidence(winner, other):
    aliases = deepcopy(winner.get('source_aliases') or [])
    alias = {key: other.get(key) for key in ('opportunity_id', 'opportunity_number', 'source', 'detail_page', 'funding_opportunity_url')}
    if alias.get('opportunity_id') != winner.get('opportunity_id') and alias not in aliases:
        aliases.append(alias)
    for value in other.get('source_aliases') or []:
        if value not in aliases and value.get('opportunity_id') != winner.get('opportunity_id'):
            aliases.append(deepcopy(value))
    if aliases:
        winner['source_aliases'] = aliases[:40]
    candidates = document_candidates(winner)
    urls = {item['url'] for item in candidates}
    for candidate in document_candidates(other):
        if candidate['url'] not in urls:
            urls.add(candidate['url'])
            candidates.append({**candidate, 'source': other.get('source'),
                               'source_opportunity_id': other.get('opportunity_id')})
    if candidates:
        winner['official_document_candidates'] = candidates[:20]
    # Preserve conflicts as a reviewable source comparison, not an override.
    conflicts = deepcopy(winner.get('duplicate_source_conflicts') or [])
    for key in ('close_date', 'award_floor', 'award_ceiling', 'cost_share_required'):
        if winner.get(key) is not None and other.get(key) is not None and winner[key] != other[key]:
            item = {'field': key, 'canonical_value': winner[key], 'alternate_value': other[key],
                    'source_opportunity_id': other.get('opportunity_id'),
                    'source_url': other.get('funding_opportunity_url') or other.get('detail_page')}
            if item not in conflicts:
                conflicts.append(item)
    if conflicts:
        winner['duplicate_source_conflicts'] = conflicts[:40]
    return winner
