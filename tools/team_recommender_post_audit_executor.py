"""One approved, exact complete-evidence inventory; data only, no dispatch."""
import copy
import json
from tools.offline_spend import identity, encoded, Deferred

PROTOCOL = 'post-audit-complete-v1'
PURPOSE = 'post-audit'
REGISTRY = '60169651eaff43c75e0eccd12167371d8131b76ed67592eaed18d3689d188126'
INPUTS_SHA256 = '5c97d02a88834328aaf00ebe4d1cf6b3a1ab6246928205351d797e9a8d40c612'


def inputs():
    from tools import team_recommender_executor as e
    raw = (e.CONFIG / 'inputs-post-audit.json').read_bytes()
    if e.sha(raw) != INPUTS_SHA256:
        raise ValueError('post_audit_unapproved_inputs')
    value = json.loads(raw)
    if value['version'] != PROTOCOL or value['registry_generation'] != REGISTRY:
        raise ValueError('post_audit_snapshot_mismatch')
    return value


def approved(request):
    from tools import team_recommender_executor as e
    e.exact_keys(request, ['protocol', 'purpose', 'body_sha256'])
    if request['protocol'] != PROTOCOL or request['purpose'] != PURPOSE:
        raise ValueError('post_audit_purpose_mismatch')
    entry = inputs()['requests'].get(request['body_sha256'])
    if entry is None or identity(entry['body']) != request['body_sha256']:
        raise ValueError('post_audit_exact_request_required')
    return entry


def judge_items(request):
    # Fixed complete questions, independent of batching/display aliases. No new
    # packet, purpose or restoration grants another logical paid attempt.
    return [item['key'] for item in approved(request)['items']]


def contract(request, settings):
    from tools import team_recommender_executor as e
    from tools.team_recommender_evidence_projection import request_body
    entry = approved(request)
    body = copy.deepcopy(entry['body'])
    data = json.loads(body['messages'][0]['content'])
    questions = [row['question']['item'] for row in entry['items']]
    expected = request_body(data['source_evidence'], [], questions,
                            (e.CONFIG / 'judge-d1.md').read_text(encoding='utf-8'))
    if body != expected or body['model'] != settings['judge_model']:
        raise ValueError('post_audit_complete_projection_changed')
    bound = len(encoded(body)) + 1024
    if bound > 24000 or not 1 <= len(questions) <= 3:
        raise Deferred('post_audit_complete_packet_bound')
    source_refs = {p['id'] for p in data['source_evidence']['passages']}
    docs = {p['person_id']:p for p in data['profile_documents']}
    aliases, refs = {}, {}
    for item in data['items']:
        people = item['candidates']
        people = set().union(*map(set, people.values())) if isinstance(people, dict) else set(people)
        aliases[item['item_id']] = item['task_type']
        refs[item['item_id']] = source_refs | {ref for pid in people
            for ref in [docs[pid]['id'], *[s['id'] for s in docs[pid]['statements']]]}
    return body, bound, aliases, refs, body['output_config']['format']['schema']
