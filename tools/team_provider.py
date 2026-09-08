"""Offline team stage routing; independent of document classification."""
import time
import json

import requests

from tools.offline_ai import Client, Ledger, config, identity, atomic_json
from tools.offline_team_contract import schemas


def routes(settings=None):
    settings = settings or config()
    selected = settings.get('production_stages', {stage: settings['production_route']
                         for stage in ('decomposition', 'adjudication', 'verification')})
    return {stage: settings['routes'][name] for stage, name in selected.items()}


def contract():
    settings = config()
    return {stage: {'route': route, 'settings': stage_settings(stage, settings), 'schema': schemas()[stage]}
            for stage, route in routes(settings).items()}


def stage_settings(stage, settings=None):
    settings = settings or config()
    return settings['stages'][stage] | settings.get('production_stage_overrides', {}).get(stage, {})


def request(provider, prompt, data):
    from scripts import build_opportunity_teams as teams
    stages = {teams.DECOMPOSE: 'decomposition', teams.ADJUDICATE: 'adjudication', teams.VERIFY: 'verification'}
    stage = stages[prompt]
    with provider.lock:
        if provider.offline is None:
            if provider.ledger is None:
                raise RuntimeError('Team generation requires an authoritative logical spend ledger')
            def post(*args, **kwargs):
                with provider.lock:
                    provider.check_budget()
                    provider.calls += 1
                    provider.counters['assessment_requests'] = provider.counters.get('assessment_requests', 0) + 1
                return requests.post(*args, **kwargs)
            provider.offline = Client(provider.ledger, provider.ledger.path.parent / 'team-responses', deadline=provider.deadline, post=post)
    route, stage_config, schema = routes()[stage], stage_settings(stage), schemas()[stage]
    key = identity({'route': route, 'stage': stage, 'config': stage_config, 'prompt': prompt, 'schema': schema, 'inputs': data})
    durable = provider.offline.cache / (key + '.json')
    optional = provider.cache / 'responses' / (key + '.json')
    if not durable.exists() and optional.exists():
        try:
            atomic_json(durable, json.loads(optional.read_bytes()))
        except (ValueError, OSError):
            pass
    value = provider.offline.json(route, stage, prompt, data, schema,
                                 lambda value: teams.validate_response(prompt, data, value), stage_config=stage_config)
    cached = json.loads(durable.read_bytes())
    atomic_json(optional, cached)
    if not hasattr(provider.provenance, 'stages'):
        provider.provenance.stages = {}
    provider.provenance.stages[stage] = {'requested': route, 'returned_model': cached['returned_model'],
                                         'request_contract': key, 'stage_config': stage_config}
    return value


def provider_names():
    return sorted({route['provider'] for route in routes().values()})
