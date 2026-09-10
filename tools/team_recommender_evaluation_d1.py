"""D1 semantic identity, complete verdict mapping and balanced comparisons. No I/O."""
import json
import hashlib


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def item_identity(scope,source,aspects,item):
    allowed={'task_type','profile_evidence','candidates','target_aspect','explanation'}
    if set(item)-allowed:raise ValueError('unblinded_or_unidentified_item_fields')
    if item['task_type']!='explanation_audit' and 'explanation' in item:raise ValueError('explanation_in_relevance')
    return identity(['D1',scope,source,aspects,item])


def map_verdicts(value,aliases):
    rows=value['verdicts']
    if len(rows)!=len(aliases) or len({v['item_id'] for v in rows})!=len(rows) or {v['item_id'] for v in rows}!=set(aliases):
        raise ValueError('incomplete_duplicate_or_unknown_verdict')
    return {aliases[v['item_id']]:v for v in rows}


def winner(label,candidates,left):
    if label in {'tie','unresolved'}:return label
    if label not in {'A','B'}:raise ValueError('invalid_comparison_grade')
    return 'left' if sorted(candidates[label])==sorted(left) else 'right'


def order_audit(first,swapped):
    if first is None or swapped is None:return 'missing'
    if 'unresolved' in (first,swapped):return 'unresolved'
    if first not in {'A','B','tie'} or swapped not in {'A','B','tie'}:raise ValueError('invalid_comparison_grade')
    return 'consistent' if {'A':'B','B':'A','tie':'tie'}[first]==swapped else 'conflict-unresolved'
