"""Read-only publication boundary for interpreted notice data.

A code merge may precede its coordinated generated package. Compare the
committed public projection with the normal, zero-request writer before any
Pages/search publication. This does not regenerate data or authorize a merge.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from scripts import extract_document_evidence as evidence, subtopic_structured
from scripts.build_catalog import compact_catalog_payload
from scripts.enrich_catalog import read_catalog
from scripts.notice_structure_cache import StructureCache

PUBLIC_FIELDS = ('document_evidence_status', 'document_evidence', 'document_search_text',
    'deadlines', 'submission_requirements', 'document_status_signals',
    'limited_submission', 'limited_submission_review', 'has_preliminary_stage',
    'preliminary_stage_type', 'preliminary_required', 'next_submission')


def verify(catalog, cache, children=None):
    stamp = catalog.get('document_evidence_generated_at') or catalog.get('generated_at')
    if not stamp:
        raise ValueError('Missing generated notice projection timestamp')
    now = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    if now.tzinfo is None:
        raise ValueError('Notice projection timestamp must include its timezone')
    def no_fetch(*_):
        raise AssertionError('Publication verification attempted source retrieval')
    with tempfile.TemporaryDirectory(prefix='notice-publication-') as directory:
        projected, _ = evidence.enrich_document_evidence(deepcopy(catalog), deepcopy(cache),
            now=now, max_documents=0, max_subtopic_documents=0, request_delay=0,
            fetcher=no_fetch, structure_cache=StructureCache(directory))
    # The catalog writer removes duplicate citations only when their exact
    # evidence reference resolves in the same record. Compare that actual
    # published representation, not the richer in-memory intermediate.
    def published_records(value):
        # Source positions may be tuples internally and JSON arrays on disk.
        return json.loads(json.dumps(compact_catalog_payload(value), default=str))['opportunities']
    published = published_records(catalog)
    rebuilt = published_records(projected)
    if [row['opportunity_id'] for row in published] != [row['opportunity_id'] for row in rebuilt]:
        raise ValueError('Notice projection changed canonical membership or order')
    changes = []
    for before, after in zip(published, rebuilt):
        fields = [key for key in PUBLIC_FIELDS if before.get(key) != after.get(key)]
        if fields:
            changes.append({'opportunity_id': str(before['opportunity_id']), 'fields': fields})
    entries = {**(cache.get('subtopic_only') or {}), **(cache.get('records') or {})}
    for identifier, child_entry in (children or {}).get('records', {}).items():
        entry = entries.get(identifier) or {}
        hgeo = (entry.get('subtopic_method') == 'hgeo_declared_topics'
                or child_entry.get('segmentation_method') == 'hgeo_declared_topics'
                or any(child.get('segmentation_method') == 'hgeo_declared_topics' for child in child_entry.get('subtopics') or []))
        if hgeo and child_entry.get('subtopics') and (entry.get('subtopic_structured') or {}).get('body_parser_version') != subtopic_structured.HGEO_BODY_VERSION:
            changes.append({'opportunity_id': identifier, 'fields': ['scientific_topic_bodies']})
    return {'schema_version': 1, 'source_requests': 0, 'provider_requests': 0,
            'publication_ready': not changes, 'changed_records': len({row['opportunity_id'] for row in changes}), 'changes': changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=Path('data/opportunities.js'))
    parser.add_argument('--cache', type=Path, default=Path('data/document_evidence.json'))
    parser.add_argument('--subtopics', type=Path, default=Path('data/subtopics.js'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--detect', action='store_true', help='Report whether a coordinated manual checkpoint is needed; never authorize publication')
    args = parser.parse_args()
    from scripts.subtopic_records import read_cache
    report = verify(read_catalog(args.catalog), json.loads(args.cache.read_bytes()), read_cache(args.subtopics))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'changes'}, sort_keys=True))
    if not report['publication_ready'] and not args.detect:
        raise SystemExit('Notice projection needs a coordinated generated package; retain the current release')


if __name__ == '__main__':
    main()
