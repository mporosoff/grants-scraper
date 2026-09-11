"""Local-only complete registry projection. No credentials, dispatch or fitting.

This is a Stage 3 schema proposal, not an enabled trusted executor route.
The existing D1F semantic rubric and 12,000-byte conservative input bound stay.
"""
import copy
import hashlib
import json

VERSION = 'complete-retained-registry-v1'
MAX_BOUND = 12000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def identity(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def person_document(person):
    """Deduplicate evidence text, not its distinct claim labels or provenance."""
    statements = {}
    for c in sorted(person['claims'], key=lambda c: c['claim_id']):
        if c['status'] != 'active':
            continue
        statements.setdefault(c['evidence'], []).append({
            'claim_id': c['claim_id'], 'revision': c['revision'],
            'label': c['label'], 'claim_type': c['type'],
            'evidence_level': c['evidence_level'], 'source_urls': sorted(c['source_urls'])})
    return {'person_id': person['id'], 'research_summary': person['research_summary'],
            'provenance': 'Retained registry summary and evidence statements; not newly retrieved or certified verbatim faculty-page quotations.',
            'statements': [{'text': text, 'claims': claims} for text, claims in sorted(statements.items())]}


def project_item(item, registry):
    allowed = {'task_type', 'candidates', 'target_aspect', 'explanation'}
    result = {k: copy.deepcopy(v) for k, v in item.items() if k in allowed}
    candidates = result['candidates']
    people = set().union(*map(set, candidates.values())) if isinstance(candidates, dict) else set(candidates)
    if isinstance(candidates, dict):
        if set(candidates) != {'A', 'B'} or len(candidates['A']) != len(candidates['B']):
            raise ValueError('matched_A_B_required')
    if result['task_type'] != 'explanation_audit' and 'explanation' in result:
        raise ValueError('no_persuasive_explanation_in_semantic_task')
    groups = list(candidates.values()) if isinstance(candidates, dict) else [candidates]
    for group in groups:
        if len(group) != len(set(group)):
            raise ValueError('duplicate_candidate')
    if any(registry[p]['status'] != 'active' or not registry[p]['auto_proposable'] for p in people):
        raise ValueError('inactive_candidate')
    result['profile_documents'] = [person_document(registry[p]) for p in sorted(people)]
    return result


def request_body(source, aspects, items, prompt):
    """Exact proposed serialized envelope; no network-capable client import."""
    passages = {p['id']: p for p in source['passages']}
    if len(passages) != len(source['passages']):
        raise ValueError('duplicate_source_reference')
    for p in passages.values():
        if hashlib.sha256(p['text'].encode()).hexdigest() != p['sha256']:
            raise ValueError('source_hash_mismatch')
    for aspect in aspects:
        if aspect['source_ref'] not in passages or aspect['text'] not in passages[aspect['source_ref']]['text']:
            raise ValueError('aspect_source_mismatch')
    refs = list(passages)
    prepared, people = [], {}
    for i, item in enumerate(items, 1):
        row = copy.deepcopy(item); row['item_id'] = 'i%02d' % i
        for person in row.pop('profile_documents'):
            pid = person['person_id']
            if pid in people and people[pid] != person:
                raise ValueError('inconsistent_person_documents')
            people[pid] = person
        prepared.append(row)
    documents = []
    for j, (_, person) in enumerate(sorted(people.items()), 1):
        # URL/registry provenance remains in the auditable input packet. The
        # judge needs the complete scientific text and labels once per person,
        # not repeated URLs or duplicate copies across independent questions.
        p = copy.deepcopy(person); p.pop('provenance'); p['id'] = 'p%d' % j
        for k, s in enumerate(p['statements'], 1):
            s['id'] = 'p%dc%d' % (j, k)
            refs.append(s['id'])
            for c in s['claims']:
                c.pop('source_urls')
        documents.append(p); refs.append(p['id'])
    verdicts = {'strong', 'plausible', 'unrelated', 'insufficient-information', 'A', 'B', 'tie', 'unresolved', 'faithful', 'unsupported', 'coherent', 'broad-unselected', 'nonresearch'}
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['verdicts'], 'properties': {
        'verdicts': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
        'required': ['item_id', 'verdict', 'evidence_ref', 'reason'], 'properties': {
            'item_id': {'type': 'string', 'enum': [x['item_id'] for x in prepared]},
            'verdict': {'type': 'string', 'enum': sorted(verdicts)},
            'evidence_ref': {'type': 'string', 'enum': sorted(set(refs))},
            'reason': {'type': 'string', 'enum': ['specific', 'transfer', 'interest', 'generic', 'missing', 'irrelevant', 'coherent', 'broad', 'nonresearch', 'overlap', 'unsupported', 'tie']}}}}}}
    data = {'projection': VERSION, 'source_evidence': source, 'aspects': aspects,
            'profile_provenance': 'Unchanged retained registry summaries and evidence statements, not newly retrieved or certified verbatim faculty-page quotations. Claim evidence levels do not certify this call/person relationship.',
            'profile_documents': documents, 'items': prepared}
    return {'model': 'claude-sonnet-5', 'system': prompt, 'max_tokens': 512,
            'thinking': {'type': 'disabled'}, 'messages': [{'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
            'output_config': {'format': {'type': 'json_schema', 'schema': schema}}}


def pack(source, aspects, keyed_items, prompt):
    """Greedy <=3 independent questions; no cropping or partial person documents."""
    packets, oversized, batch = [], [], []
    def flush():
        if batch:
            body = request_body(source, aspects, [v for _, v in batch], prompt)
            packets.append({'keys': [k for k, _ in batch], 'body': body,
                            'input_bound': len(encoded(body)) + 1024})
            batch.clear()
    for key, item in keyed_items:
        alone = len(encoded(request_body(source, aspects, [item], prompt))) + 1024
        if alone > MAX_BOUND:
            flush(); oversized.append({'key': key, 'input_bound': alone}); continue
        proposed = batch + [(key, item)]
        if len(proposed) > 3 or len(encoded(request_body(source, aspects, [v for _, v in proposed], prompt))) + 1024 > MAX_BOUND:
            flush()
        batch.append((key, item))
    flush()
    return packets, oversized


def remap_winner(verdict, swapped):
    if verdict not in {'A', 'B', 'tie', 'unresolved'}:
        raise ValueError('invalid_comparison_verdict')
    return {'A': 'B', 'B': 'A'}.get(verdict, verdict) if swapped else verdict
