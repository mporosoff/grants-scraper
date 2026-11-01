"""Reconcile a duplicated program total only from a complete owned award table."""
import re
from urllib.parse import urlparse


def _positive(value):
    return type(value) in (int, float) and 0 < value < float('inf')


def _same_document(requested, served):
    if requested == served and requested:
        return True
    urls = [urlparse(value or '') for value in (requested, served)]
    return all(u.scheme == 'https' and not u.username and not u.password
        and (u.hostname == 'grants.gov' or re.fullmatch(r'apply[0-9]+\.grants\.gov', u.hostname or ''))
        and not u.query and not u.fragment for u in urls) and bool(re.fullmatch(
            r'/grantsws/rest/opportunity/att/download/[1-9][0-9]*', urls[0].path)) and urls[0].path == urls[1].path


def reconcile_program_total(record, entry):
    """Return a reversible ceiling correction; ordinary conflicting sources stay put.

    The notice must account for the entire budget with disjoint named topic
    totals and one compatible per-award range for every one of those topics.
    A partial table, mismatched document, different basis or conditional amount
    cannot establish the largest award offered by the whole opportunity.
    """
    document = entry.get('document') or {}
    total = record.get('total_program_funding')
    if (record.get('source') != 'Grants.gov' or not entry.get('extractor_identity')
        or entry.get('status') != 'current' or not _positive(total)
        or record.get('award_ceiling') != total
        or not _positive(record.get('expected_number_of_awards'))
        or record['expected_number_of_awards'] <= 1
        or not re.fullmatch('[a-f0-9]{64}', str(document.get('sha256') or ''))
        or not _same_document(record.get('primary_document_url'), document.get('url'))):
        return None

    facts = [fact for fact in entry.get('facts') or []
             if fact.get('type') in {'program_funding', 'award_range'}]
    budgets, ranges, overall = {}, {}, []
    for fact in facts:
        citation = fact.get('citation') or {}
        reference = citation.get('structural_reference') or {}
        if (citation.get('sha256') != document['sha256']
            or citation.get('document_url') != document['url']
            or not reference.get('block_id') or not citation.get('quote')
            or fact.get('fact_contract') != 'typed-notice-facts-1'
            or fact.get('source_authority') != 'machine_extracted_official_document'
            or fact.get('currency') != 'USD'
            or any(fact.get(key) for key in ('applicant_condition', 'funding_basis', 'estimate_kind',
                                           'cycle', 'application_class'))):
            return None
        track = fact.get('track')
        if track:
            track_citation = fact.get('track_citation') or {}
            if (track_citation.get('sha256') != document['sha256']
                or track_citation.get('document_url') != document['url']):
                return None
        if fact['type'] == 'program_funding':
            if fact.get('basis') != 'program_total' or not _positive(fact.get('value')):
                return None
            if not track:
                if fact['value'] != total:
                    return None
                overall.append(fact)
                continue
            if track in budgets and budgets[track]['value'] != fact['value']:
                return None
            budgets[track] = fact
        else:
            bounds = fact.get('value') or {}
            if (not track or fact.get('basis') != 'total_project'
                or fact.get('cost_basis') not in {'total', 'unspecified'}
                or not all(_positive(bounds.get(key)) for key in ('minimum', 'maximum'))
                or bounds['minimum'] > bounds['maximum']):
                return None
            if track in ranges and ranges[track]['value'] != bounds:
                return None
            ranges[track] = fact
    if (not overall or not budgets or set(budgets) != set(ranges)
        or sum(fact['value'] for fact in budgets.values()) != total):
        return None
    # All topic totals/ranges must belong to one native table/page. Separate
    # cycles or other funding sections are not an exhaustive shared schedule.
    owned_rows = list(budgets.values()) + list(ranges.values())
    pages = {fact['citation'].get('page') for fact in owned_rows}
    if len(pages) != 1 or None in pages:
        return None
    ceiling = max(fact['value']['maximum'] for fact in ranges.values())
    if ceiling >= total or any(ranges[t]['value']['maximum'] > budgets[t]['value'] for t in ranges):
        return None
    return {'status': 'program_total_reconciled', 'field': 'award_ceiling',
        'structured_value': total, 'notice_value': ceiling,
        'basis': 'maximum_across_complete_topic_award_ranges',
        'document_sha256': document['sha256'],
        'evidence_ids': sorted({fact['id'] for fact in overall + owned_rows}),
        'tracks': {track: ranges[track]['value'] for track in sorted(ranges)}}
