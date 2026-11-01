"""Narrow, quote-proved corrections; never a source reparse or new fact store."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from scripts import notice_duration

VERSION = 'notice-fact-guards-1'
COMPONENT_NAMES = {
    'Letters of support': r'letters?\s+of\s+(?:support(?:\s*/\s*commitment)?|commitment)(?:\s+or\s+collaboration)?',
    'Data management plan': r'data\s+management(?:\s+and\s+sharing)?\s+plan',
    'Logic model': r'logic\s+models?',
}


def component_role_condition(text, subject):
    """A complete same-component obligation restricted to a class of applicants."""
    name = COMPONENT_NAMES.get(subject)
    if not name:
        return False
    # The whole role, condition and required attachment must survive in one
    # clause. A clipped quote or a neighboring component cannot supply scope.
    pattern = (r'\b(?:Applicants|Proposers)\s+'
               r'(?:that|who|including|using|with)\s+[^.!?;\u2026\u2022]{1,180}?'
               r'\s+must\s+(?:submit|include|provide)\s+(?:(?:an?|the)\s+)?'
               rf'{name}\b')
    return bool(re.search(pattern, text, re.I))


def component_not_required(text, subject):
    """Only a complete, unqualified assertion about this named component."""
    name = COMPONENT_NAMES.get(subject)
    if not name:
        return False
    # Roles, preliminary stages, clipped qualifiers and "not required to be X"
    # cannot establish that the component itself is unnecessary.
    ending = (r'\s*(?:(?:as\s+part\s+of|with|for)\s+(?:the\s+)?'
              r'(?:application|proposal))?\s*(?=[.)!?;]|$)')
    direct = (rf'\b{name}\b\s*(?:\([A-Z]{{2,12}}\)\s*)?'
              r'(?:(?:is|are)\s+)?(?:encouraged(?:\s+from\s+partners)?\s+but\s+(?:(?:is|are)\s+)?)?'
              r'not\s+(?:required|mandatory|necessary)' + ending)
    inverse = (r'\bnot\s+(?:required|mandatory|necessary)\s+to\s+(?:submit|include|provide)\s+'
               rf'(?:(?:an?|the)\s+)?{name}\b' + ending)
    for pattern in (direct, inverse):
        for match in re.finditer(pattern, text, re.I):
            # A condition in the same sentence cannot become a universal rule.
            prefix = re.split(r'[.!?;\n]', text[:match.start()])[-1]
            if not re.search(r'\b(?:if|unless|when|only)\b', prefix, re.I):
                return True
    return False


def personnel_rate(text, start, end):
    """A monetary token's own rate/unit or retained labor-table header."""
    if re.match(r'\s*(?:/\s*(?:hr|hour)\b|per\s+hour\b)', text[end:], re.I):
        return True
    prefix = text[max(0, start - 280):start]
    headers = list(re.finditer(r'\b(?:direct\s+)?hourly\s+rate\b', prefix, re.I))
    if not headers or not re.search(r'\b(?:employee\s+name|labor\s+category|total\s+direct\s+labor)\b', prefix, re.I):
        return False
    # An independently labeled later funding field keeps its own authority.
    return not re.search(r'\b(?:program\s+(?:funding|budget)|funding\s+available)\b',
                         prefix[headers[-1].end():], re.I)


def repair_facts(facts, document):
    """Withhold only demonstrably false assertions bound to this document.

    Shortened evidence cannot prove missing context. All unrelated facts,
    citations, identities and clocks remain exact; nothing is re-extracted.
    """
    retained, changes = [], []
    for fact in facts:
        citation = fact.get('citation') or {}
        quote = citation.get('quote') or ''
        reason = None
        bound = (document.get('url') and document.get('sha256')
                 and citation.get('document_url') == document['url']
                 and citation.get('sha256') == document['sha256'])
        if bound and fact.get('type') == 'application_component' and fact.get('obligation') == 'required':
            if component_not_required(quote, fact.get('subject') or fact.get('label')):
                reason = 'component_explicit_not_required'
            elif not fact.get('applicant_condition') and component_role_condition(
                    quote, fact.get('subject') or fact.get('label')):
                reason = 'component_applicant_condition_missing'
        if bound and notice_duration.unscoped_duration(fact):
            reason = 'project_duration_scope_missing'
        if bound and fact.get('type') == 'program_funding':
            for token in re.finditer(r'\$\s*(\d[\d,]*(?:\.\d+)?)', quote):
                try:
                    same = Decimal(token[1].replace(',', '')) == Decimal(str(fact.get('value')))
                except InvalidOperation:
                    same = False
                if same and personnel_rate(quote, token.start(), token.end()):
                    reason = 'personnel_rate_not_program_funding'
                    break
        if reason:
            changes.append({'fact_id': fact['id'], 'reason': reason})
        else:
            retained.append(deepcopy(fact))
    return retained, changes


def repair_entry(entry):
    """Mutate only facts and a bounded correction receipt, idempotently."""
    document = entry.get('document') or {}
    facts, changes = repair_facts(entry.get('facts') or [], document)
    if changes:
        prior = entry.get('fact_guard') or {}
        withheld = deepcopy(prior.get('withheld') or []) if prior.get('version') == VERSION else []
        withheld.extend(change for change in changes if change not in withheld)
        entry['facts'] = facts
        entry['fact_guard'] = {'version': VERSION, 'source_retrieved': False,
            'document_url': document['url'], 'document_sha256': document['sha256'], 'withheld': withheld}
    return changes
