"""Read-only source-annotated parsing acceptance; never fetches or calls AI.

Bounded excerpts exercise semantic contracts. Full original-source extraction
is measured separately in the private corpus audit. An unannotated holdout is
pending evidence, never a passing empty fixture.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts import extract_document_evidence as evidence, subtopic_structured
from scripts.nsf_funding import parse_nsf_funding_page


def contains(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and contains(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(contains(item, value) for item in actual) for value in expected)
    return type(actual) is type(expected) and actual == expected


def validate(manifest_path, *, split='all'):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('notices'), list):
        raise ValueError('Invalid parsing fixture manifest')
    identifiers = [row.get('opportunity_id') for row in manifest['notices']]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError('Duplicate acceptance notice')
    counts = Counter()
    results = []
    for row in manifest['notices']:
        if split != 'all' and row.get('split') != split:
            continue
        counts['notices'] += 1
        result = {'opportunity_id': row['opportunity_id'], 'split': row['split'], 'checks': []}
        fixtures = row.get('fixtures') or []
        if not fixtures:
            counts['pending_notices'] += 1
            result['status'] = 'pending_source_annotation'
            results.append(result)
            continue
        for item in fixtures:
            path = (manifest_path.parent / item['path']).resolve()
            if not path.is_relative_to(manifest_path.parent) or path.suffix != '.json':
                raise ValueError('Fixture path must stay within the acceptance directory')
            raw = path.read_bytes()
            if len(raw) > 100_000 or hashlib.sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('Fixture size or content hash mismatch')
            fixture = json.loads(raw)
            source = fixture.get('source') or {}
            if (not str(source.get('url', '')).startswith('https://')
                or not re_full_hash(source.get('sha256')) or not source.get('retrieved_at')
                or not fixture.get('annotations')):
                raise ValueError('Every fixture needs an original source receipt and independent annotations')
            document = {'url': source['url'], 'name': fixture.get('document_name'), 'sha256': source['sha256']}
            queue = []
            if fixture['format'] == 'html_excerpt':
                containers, _ = evidence.extract_html_sections(fixture['text'].encode())
                facts = evidence.extract_document_facts(row, containers, document, source['retrieved_at'], queue)
            elif fixture['format'] == 'pdf_text_excerpt':
                containers = fixture['containers']
                facts = evidence.extract_document_facts(row, containers, document, source['retrieved_at'], queue)
            elif fixture['format'] == 'hgeo_section_excerpt':
                facts = subtopic_structured.parse_hgeo(fixture['text'], row['opportunity_number'])
            elif fixture['format'] == 'nsf_synopsis_excerpt':
                facts = [parse_nsf_funding_page(fixture['text'])]
            else:
                raise ValueError('Unsupported acceptance fixture format')
            for annotation in fixture['annotations']:
                if not annotation.get('location') or not annotation.get('rationale'):
                    raise ValueError('Acceptance annotations require a source location and rationale')
                required = annotation.get('require')
                forbidden = annotation.get('forbid')
                if (required is None) == (forbidden is None):
                    raise ValueError('Each annotation must require or forbid one fact contract')
                substrings = annotation.get('contains_text') or {}
                if not (required or forbidden or substrings):
                    raise ValueError('An empty acceptance assertion is not evidence')
                pool = queue if annotation.get('target') == 'review_queue' else facts
                match = any(contains(fact, required if required is not None else forbidden)
                            and all(isinstance(fact.get(key), str) and value in fact[key] for key, value in substrings.items())
                            for fact in pool)
                passed = match if required is not None else not match
                kind = 'valid_information_retained_or_recovered' if required is not None else 'incorrect_assertion_absent'
                counts[kind if passed else 'missing_positive' if required is not None else 'incorrect_assertion_published'] += 1
                result['checks'].append({'fixture': item['path'], 'location': annotation['location'],
                                         'kind': kind, 'passed': passed, 'expected': required if required is not None else forbidden})
        result['status'] = 'pass' if all(check['passed'] for check in result['checks']) else 'fail'
        results.append(result)
    return {'schema_version': 1, 'selection_sha256': manifest.get('selection_sha256'), 'split': split,
            'source_requests': 0, 'provider_requests': 0, 'counts': dict(counts), 'notices': results,
            'passed': bool(results) and all(row['status'] == 'pass' for row in results)}


def re_full_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--split', choices=['development', 'holdout', 'all'], default='all')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.manifest, split=args.split)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['counts'], sort_keys=True))
    if not report['passed']:
        raise SystemExit('Parsing acceptance has failures or pending source annotations; inspect report')


if __name__ == '__main__':
    main()
