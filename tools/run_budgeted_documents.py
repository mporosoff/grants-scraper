"""Run document extraction with the bounded active Cov4 production contract."""
import json
import os
from pathlib import Path
import runpy
import sys


from tools.offline_spend import production_ledger, require_production_service, check_run_transport, response_cache, atomic_json


def instrument(ledger, cache, classify, *, replay=False):
    """Use the same active classifier and structured client in production/evaluation."""
    from tools.offline_ai import Client
    def bounded(candidate, *, api_key=None, session=None):
        if replay:
            from tools.evaluate_team_prompt_repair import ReplayClient
            client = ReplayClient(cache)
            client.ledger = ledger
        else:
            client = Client(ledger, cache, post=session.post if session is not None else None)
        return classify(candidate, api_key=api_key, session=session, offline_client=client)
    return bounded


def main():
    from scripts import subtopic_cov4 as gate
    state = Path(os.environ['OFFLINE_AI_STATE'])
    mode = os.environ['TEAM_MODE']
    ledger = production_ledger(state, mode)
    classify = instrument(ledger, response_cache(ledger, 'cov4'), gate.classify_fundability)
    start = len(ledger.read()['requests'])
    def qualified(candidate, **kwargs):
        try:
            require_production_service('cov4', ledger)
            check_run_transport(ledger, start)
        except RuntimeError as error:
            return gate._unresolved('service_unavailable', detail=type(error).__name__)
        return classify(candidate, **kwargs)
    gate.classify_fundability = qualified
    # The classifier is shared with qualification; native/reference ownership
    # proofs and publication confidence remain separate deterministic gates.
    sys.argv[0] = 'scripts.extract_document_evidence'
    try:
        runpy.run_module('scripts.extract_document_evidence', run_name='__main__', alter_sys=True)
    finally:
        atomic_json(state / 'usage-summary.json', ledger.summary())


if __name__ == '__main__':
    main()
