"""Release checks that compare retained official evidence with public surfaces."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import subprocess
from xml.etree import ElementTree

from scripts import extract_document_evidence as evidence, notice_fact_guards, notice_schedule
from scripts.build_catalog import CATALOG_GLOBAL
from scripts.build_changes import record_id
from scripts.build_feeds import entry_id, summarize
from scripts.currentness import record_is_current
from scripts.source_documents import is_verified_grants_closure, nonprimary_document_reason
from scripts.submission_schedule import FULL, PRELIMINARY, events, valid_date


CHANGE_FIELDS = ('status', 'close_date', 'deadlines', 'submission_requirements', 'next_submission',
                 'source_aliases', 'primary_document_url')
RECORD_FIELDS = (*CHANGE_FIELDS, 'opportunity_number', 'agency_code', 'primary_document_name',
                 'funding_opportunity_url', 'document_urls', 'official_document_candidates',
                 'document_evidence_status', 'document_evidence')
ATOM = '{http://www.w3.org/2005/Atom}'


def protected_catalog():
    """Read the immutable checkout before its candidate overlay."""
    raw = subprocess.check_output(['git', 'show', 'HEAD:data/opportunities.js']).decode('utf-8')
    prefix = f'globalThis.{CATALOG_GLOBAL}='
    _, separator, payload = raw.partition(prefix)
    if not separator:
        raise ValueError('Invalid protected catalog for publication comparison')
    catalog = json.loads(payload.strip().removesuffix(';'))
    if len(catalog['opportunities']) != catalog['record_count']:
        raise ValueError('Protected publication catalog record count changed')
    return catalog


def is_protected_catalog(catalog_path, candidate_id):
    manifest = json.loads(subprocess.check_output(['git', 'show', 'HEAD:release/candidate.json']))
    return (manifest.get('candidate_id') == candidate_id
            and manifest.get('files', {}).get('data/opportunities.js')
            == hashlib.sha256(catalog_path.read_bytes()).hexdigest())


def _finding(identifier, reason, fields, **details):
    return {'opportunity_id': identifier, 'reason': reason, 'fields': list(fields), **details}


def _owned(citation, document):
    return bool(document.get('url') and document.get('sha256')
                and citation.get('document_url') == document['url']
                and citation.get('sha256') == document['sha256'])


def _scope(row):
    return (row.get('application_class') or 'unspecified', row.get('cycle'), row.get('track'))


def _nonprimary(record, public, cached):
    url = record.get('primary_document_url')
    nominated = [{'url': url, 'name': record.get('primary_document_name')}]
    nominated.extend(row for row in (record.get('document_urls') or [])
                     if isinstance(row, dict) and (row.get('url') or row.get('download_url')) == url)
    nominated.extend(row for row in (record.get('official_document_candidates') or [])
                     if row.get('url') == url)
    if url and cached.get('source_url') == url:
        nominated.append(cached.get('document') or {})
    if url:
        for row in nominated:
            if reason := nonprimary_document_reason(row):
                return reason, 'primary_document_url'
    if reason := nonprimary_document_reason(public.get('document') or {}):
        return reason, 'document_evidence'
    return None


def _mandatory_prerequisites(record, cached):
    source = evidence.source_for_record(record)
    if (not source or cached.get('status') != 'current'
            or cached.get('source_signature') != evidence.source_signature(record, source)):
        return []
    if (record.get('source') == 'ARPA-H'
            and any(fact.get('type') == 'deadline' and not fact.get('arpa_summary_version')
                    for fact in cached.get('facts') or [])):
        cached = deepcopy(cached)
        notice_schedule.repair_cached_arpa_summary(evidence, record, cached)
    document = cached.get('document') or {}
    facts = [fact for fact in cached.get('facts') or [] if fact.get('type') == 'deadline'
             and valid_date(fact.get('date')) and _owned(fact.get('citation') or {}, document)]
    scheduled = events(record)
    findings = []
    for fact in facts:
        stage, deadline, scope = fact.get('deadline_kind'), fact['date'], _scope(fact)
        if (stage not in PRELIMINARY or fact.get('required') is not True
                or fact.get('date_qualifier') in ('anticipated', 'recommended')):
            continue
        citation = fact.get('citation') or {}
        label = (citation.get('structural_reference') or {}).get('field_label') or ''
        requirement = fact.get('requirement_citation') or {}
        if (not _owned(requirement, document) and notice_schedule.obligation(label)[1] is not True):
            continue
        # Compare only an ordered, scope-proven pair from this same document.
        full = {row['date'] for row in facts if row.get('deadline_kind') in FULL
                and row.get('date_qualifier') not in ('anticipated', 'recommended')
                and _scope(row) == scope and row['date'] > deadline}
        if len(full) != 1:
            continue
        scoped = [row for row in scheduled if _scope(row) == scope]
        gate = any(row.get('kind') == stage and row.get('date') == deadline
                   and row.get('required') is True for row in scoped)
        final_dates = {row.get('date') for row in scoped if row.get('kind') in FULL}
        same_day_full = any(row.get('deadline_kind') in FULL and _scope(row) == scope
                            and row['date'] == deadline for row in facts)
        if not gate or not full <= final_dates or (deadline in final_dates and not same_day_full):
            findings.append(_finding(record_id(record), 'official_prerequisite_differs_from_catalog',
                ('deadlines', 'submission_requirements'), stage=stage, date=deadline,
                full_dates=sorted(full), evidence_id=fact['id']))
    return findings


def changed_record_findings(catalog, cache, previous, as_of):
    prior = {record_id(row): row for row in previous['opportunities']}
    findings = []
    for record in catalog['opportunities']:
        identifier = record_id(record)
        if is_verified_grants_closure(identifier, record.get('opportunity_number'),
                                      record.get('agency_code'), as_of):
            findings.append(_finding(identifier, 'verified_closed_opportunity_still_present', ('status',)))
        if all(record.get(key) == prior.get(identifier, {}).get(key) for key in RECORD_FIELDS):
            continue
        public = record.get('document_evidence') or {}
        cached = (cache.get('records') or {}).get(identifier) or {}
        invalid = _nonprimary(record, public, cached)
        if invalid:
            reason, field = invalid
            findings.append(_finding(identifier, reason, (field,)))
        _, facts = notice_fact_guards.repair_facts(
            public.get('facts') or [], public.get('document') or {})
        for fact in facts:
            findings.append(_finding(identifier, fact['reason'], ('document_evidence',),
                                     evidence_id=fact['fact_id']))
        findings.extend(_mandatory_prerequisites(record, cached))
    return findings


def change_snapshot_findings(catalog, feed):
    records = {record_id(row): row for row in catalog['opportunities']}
    findings = []
    for event in feed['events']:
        if event['changed_at'] != catalog['generated_at'] or event['type'] == 'closed_or_removed':
            continue
        identifier = str(event['opportunity_id'])
        record, snapshot = records.get(identifier), event['record']
        fields = [key for key in CHANGE_FIELDS if record is None or record.get(key) != snapshot.get(key)]
        if fields:
            findings.append(_finding(identifier, 'current_change_snapshot_differs_from_catalog',
                                     fields, event_id=event['id'], event_type=event['type']))
    return findings


def static_feed_findings(catalog, feed_dir, as_of):
    """Check actual Atom entries against canonical membership and the audit day."""
    records = {entry_id(row): row for row in catalog['opportunities']}
    generation_day = date.fromisoformat(catalog['generated_at'][:10])
    paths = [feed_dir / 'all.xml', *sorted((feed_dir / 'source-type').glob('*.xml')),
             *sorted((feed_dir / 'topic').glob('*.xml'))]
    findings = []
    for path in paths:
        name = path.relative_to(feed_dir).as_posix()
        for entry in ElementTree.parse(path).iterfind(f'{ATOM}entry'):
            identifier = entry.findtext(f'{ATOM}id')
            record = records.get(identifier)
            if record is None:
                findings.append(_finding(identifier, 'static_feed_entry_has_no_catalog_record', ('feed',), feed=name))
                continue
            current, reason = record_is_current(record, as_of)
            if not current:
                findings.append(_finding(record_id(record), 'static_feed_entry_is_not_current', ('feed',),
                                         feed=name, currentness_reason=reason))
                continue
            if generation_day < as_of:
                expected = summarize(record, as_of).replace('\u2014', '-').replace('\u2013', '-')
                if entry.findtext(f'{ATOM}summary') != expected:
                    before = summarize(record, generation_day).replace('\u2014', '-').replace('\u2013', '-')
                    if expected != before and entry.findtext(f'{ATOM}summary') == before:
                        findings.append(_finding(record_id(record), 'static_feed_entry_has_stale_submission',
                                                 ('feed', 'next_submission'), feed=name))
    return findings
