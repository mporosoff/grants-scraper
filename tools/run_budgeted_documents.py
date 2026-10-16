"""Run document extraction with the bounded active Cov4 production contract."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys


from tools.offline_spend import production_ledger, require_production_service, check_run_transport, response_cache, atomic_json, config


def instrument(ledger, cache, classify, *, replay=False, work_budget=None):
    """Use the same active classifier and structured client in production/evaluation."""
    from tools.offline_ai import Client
    def bounded(candidate, *, api_key=None, session=None):
        identifier = str(candidate.get('parent_record_id') or candidate.get('parent_opportunity_number')
                         or candidate.get('opportunity_id') or '')
        guard = work_budget.guard('notice_classification', identifier) if work_budget is not None else nullcontext()
        with guard:
            if replay:
                from tools.evaluate_team_prompt_repair import ReplayClient
                client = ReplayClient(cache)
                client.ledger = ledger
            else:
                # Read inside the candidate's unit so transport/cache work gets
                # that cap as well as the unchanged global document deadline.
                client = Client(ledger, cache, deadline=work_budget.deadline if work_budget is not None else float('inf'),
                                post=session.post if session is not None else None)
            return classify(candidate, api_key=api_key, session=session, offline_client=client)
    return bounded


def main():
    from scripts import extract_document_evidence as extractor
    # This step is allowed to fail in the workflow. Close publication before
    # fallible ledger/config/timer setup as well as before extraction begins.
    extractor.mark_document_work_incomplete(phase='initializing')
    from scripts import subtopic_cov4 as gate
    from scripts.document_work_budget import WorkBudget, WorkTimedOut
    state = Path(os.environ['OFFLINE_AI_STATE'])
    mode = os.environ['TEAM_MODE']
    ledger = production_ledger(state, mode)
    from tools import generation_document_checkpoint as checkpoint
    from tools.release_candidate import ROOT
    run, attempt = os.environ.get('GITHUB_RUN_ID'), os.environ.get('GITHUB_RUN_ATTEMPT')
    checkpoint_enabled = bool(run or attempt)
    if checkpoint_enabled:
        checkpoint.restore(ROOT, state, run, attempt)
    budget = WorkBudget(config()['max_seconds'])
    original = gate.classify_fundability
    classify = instrument(ledger, response_cache(ledger, 'cov4'), original, work_budget=budget)
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
    attempted = False
    try:
        with budget.guard('document_phase', finalize=True, seconds=config()['max_seconds']):
            attempted = True
            return extractor.main(work_budget=budget)
    except WorkTimedOut:
        return extractor.safe_timeout_fallback(work_budget=budget)
    finally:
        gate.classify_fundability = original
        atomic_json(state / 'usage-summary.json', ledger.summary())
        if checkpoint_enabled and attempted:
            checkpoint.capture(ROOT, state, run, attempt)


if __name__ == '__main__':
    sys.exit(main())
