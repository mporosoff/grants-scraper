"""Deterministic submission selection shared by catalog/feed/change consumers.

The browser/Worker implementation in assets/submission-schedule.js is checked
against these same fixtures. Selection does not alter source close_date or
infer applicant eligibility. It explains explicitly owned prerequisites.
"""
from copy import deepcopy
from datetime import date
import re

VERSION = 2
PRELIMINARY = {'letter_of_intent', 'concept_paper', 'white_paper', 'preapplication', 'preproposal', 'abstract'}
FULL = {'application', 'estimated_application', 'full_application', 'proposal'}
KINDS = PRELIMINARY | FULL | {'submission', 'internal'}


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def events(record):
    declared = (record.get('deadlines') or []) + (record.get('submission_requirements') or [])
    result = [deepcopy(event) for event in declared
              if isinstance(event, dict) and event.get('kind') in KINDS
              and event.get('date_qualifier') != 'administrative']
    if (not any(event.get('kind') in FULL | {'submission'} or event.get('date') == record.get('close_date') for event in result)
        and not any(isinstance(event, dict) and event.get('date_qualifier') == 'administrative'
                    and event.get('date') == record.get('close_date') for event in declared)
        and valid_date(record.get('close_date'))):
        result.append({'kind': 'submission' if record.get('close_date_kind') == 'submission_window_end' else 'application',
                       'date': record['close_date'], 'time': record.get('deadline_time'),
                       'timezone': record.get('deadline_timezone'), 'source': record.get('source')})
    return result


def compatible(left, right):
    return all(not left.get(key) or not right.get(key) or left[key] == right[key]
               or 'unspecified' in (left[key], right[key]) for key in ('application_class', 'cycle', 'track'))


def required_gate(event):
    # A source-listed internal submission deadline is an institutional gate,
    # even when the older listing did not separately encode required=True.
    return event.get('required') is True or (event.get('kind') == 'internal' and event.get('required') is not False)


def next_submission(record, as_of=None, *, application_class='new'):
    today = (as_of or date.today()).isoformat() if not isinstance(as_of, str) else as_of
    if not valid_date(today):
        raise ValueError('Submission selection requires an ISO calendar date')
    all_events = events(record)
    relevant = [event for event in all_events
                if event.get('application_class') in (None, 'unspecified', application_class)]
    future = sorted((event for event in relevant if valid_date(event.get('date')) and event['date'] >= today),
                    key=lambda event: (event['date'], event.get('kind', ''), event.get('cycle') or '', event.get('track') or ''))
    if not future:
        future = sorted((event for event in relevant if event.get('kind') in FULL and event.get('rolling') is True
                         and event.get('date') is None), key=lambda event: (event.get('cycle') or '', event.get('track') or ''))
    result = {'version': VERSION, 'as_of': today, 'application_class': application_class,
              'date': None, 'event': None, 'access': 'not_listed', 'prerequisites': []}
    if not future:
        full = [event for event in relevant if event.get('kind') in FULL and valid_date(event.get('date'))]
        latest = max((event['date'] for event in full), default=None)
        recommended = bool(latest) and all(event.get('date_qualifier') in {'recommended', 'anticipated'} for event in full if event['date'] == latest)
        other_classes = [event for event in all_events if valid_date(event.get('date')) and event['date'] >= today]
        result['access'] = (('resubmission_only' if all(event.get('application_class') == 'resubmission' for event in other_classes)
                             else 'verify_stage') if other_classes
                            else 'verify_stage' if recommended
                            else 'closed' if any(valid_date(event.get('date')) for event in relevant)
                            else 'rolling' if record.get('rolling') else 'not_listed')
        return result
    chosen = future[0]
    result.update(date=chosen.get('date'), event=chosen, access='rolling' if chosen.get('rolling') is True and chosen.get('date') is None else 'open')
    if chosen.get('kind') == 'submission' or chosen.get('date_qualifier') == 'anticipated':
        result['access'] = 'verify_stage'
    preliminary = [event for event in relevant if compatible(event, chosen) and event.get('required') is not False
                   and ((chosen.get('kind') in FULL and event.get('kind') in PRELIMINARY)
                        or (chosen.get('kind') != 'internal' and event.get('kind') == 'internal'))]
    if chosen.get('kind') in FULL or preliminary:
        # Without explicit cycle identity, several historical cycles cannot be
        # joined by nearest-date proximity. Keep the full date and qualify access.
        if not chosen.get('cycle') and len({event.get('cycle') for event in preliminary if event.get('cycle')}) > 1:
            result['access'] = 'verify_prerequisite'
        else:
            result['prerequisites'] = preliminary
            uncertain = {'recommended', 'anticipated'}
            if any(required_gate(event) and event.get('date_qualifier') not in uncertain
                   and valid_date(event.get('date')) and event['date'] < today for event in preliminary):
                result['access'] = 'prerequisite_closed'
            elif any(required_gate(event) and (event.get('date_qualifier') in uncertain
                     or (not valid_date(event.get('date')) and event.get('rolling') is not True)) for event in preliminary):
                result['access'] = 'verify_prerequisite'
            elif any(event.get('required') is None and not required_gate(event) for event in preliminary):
                result['access'] = 'verify_prerequisite'
        if (chosen.get('kind') in FULL and result['access'] != 'prerequisite_closed'
            and not any(event.get('kind') in PRELIMINARY for event in all_events)
            and record.get('has_preliminary_stage') is True and record.get('preliminary_required') is not False):
            # A source-declared preliminary stage with no recovered event is
            # unresolved access, not proof that a new applicant can enter now.
            result['access'] = 'verify_prerequisite'
        if chosen.get('kind') in FULL and (chosen.get('invitation_required') is True or chosen.get('prerequisite') == 'invitation'
            or any(event.get('kind') in FULL and event.get('date') is None and compatible(event, chosen)
                   and event.get('invitation_required') is True for event in relevant)):
            result['access'] = 'invitation_required'
    return result


def _invitation_evidence(record):
    title = record.get('title')
    quote = title[:500] if isinstance(title, str) else ''
    evidence = {'source_field': 'title', 'quote': quote,
        'source_url': record.get('detail_page') or record.get('funding_opportunity_url')
                      or record.get('primary_document_url')}
    if re.search(r'\bInvited\s+to\s+Apply\b', quote, re.I):
        return evidence
    if not re.search(r'\bSingle[ -]Source\b', quote, re.I):
        return None
    # A single-source title alone names restricted eligibility, not an invitation.
    # These source clauses explicitly identify the same single-source notice.
    pattern = re.compile(
        r'\bsingle[ -]source(?:\s+(?:competition|NOFO))?\s+that\s+will\s+invite\s+'
        r'(?:an?\s+)?applications?(?:\(s\))?\s+from\s+(?:(?:an?|the)\s+)?'
        r'eligible\s+organizations?(?:\(s\))?\s+to\s+apply\b|'
        r'\bNotice\s+of\s+Funding\s+Opportunity\s+\(NOFO\)\s+invites\s+a\s+'
        r'Single[ -]Source\s+application\s+for\s+the\s+eligible\s+organization\b', re.I)
    for field in ('description', 'eligibility_text'):
        value = record.get(field)
        match = pattern.search(value[:12000]) if isinstance(value, str) else None
        if match and len(match.group()) <= 500:
            evidence['restriction'] = {'source_field': field, 'quote': match.group()}
            return evidence
    return None


def project_invitation_access(record):
    """Project explicit notice-wide invitation evidence onto full submissions.

    Invitations mentioned by an ordinary open or staged call establish no global
    restriction. A single-source classification also requires its explicit clause.
    """
    result = deepcopy(record)
    evidence = _invitation_evidence(record)
    if evidence is None:
        return result
    declared = (result.get('deadlines') or []) + (result.get('submission_requirements') or [])
    # Preserve collection ownership and let the existing selector materialize
    # its close-date fallback before adding the access qualification.
    for event in events(result):
        if event not in declared:
            result['deadlines'] = (result.get('deadlines') or []) + [event]
    for field in ('deadlines', 'submission_requirements'):
        for event in result.get(field) or []:
            if isinstance(event, dict) and event.get('kind') in FULL:
                event.update(invitation_required=True, prerequisite='invitation',
                             invitation_evidence=deepcopy(evidence))
    return result


def project_two_step_prerequisite(record):
    """Retain one explicitly required, dated Step-1 before a matching Step-2.

    This source-owned pair does not infer numbered stages from document headings
    or apply an unrelated preliminary date to a full submission.
    """
    result = deepcopy(record)
    text = record.get('description')
    if not isinstance(text, str):
        return result
    text = text[:12000]
    obligations = list(re.finditer(r'\bonly proposers that submit a Step[ -]1 proposal '
        r'will be eligible to submit a Step[ -]2 proposal\b', text, re.I))
    if len(obligations) != 1:
        return result
    from scripts.extract_document_evidence import DATE_RE, parse_document_date
    pairs = list(re.finditer(r'\bStep[ -]1 proposals are due (?P<first>' + DATE_RE.pattern
        + r'),? and Step[ -]2 proposals are due (?P<second>' + DATE_RE.pattern + r')', text, re.I))
    labels = re.findall(r'\bStep[ -][12] proposals? (?:are|is) due\b', text, re.I)
    if len(pairs) != 1 or len(labels) != 2:
        return result
    pair = pairs[0]
    first, second = parse_document_date(pair['first']), parse_document_date(pair['second'])
    if not first or not second or first >= second or second != record.get('close_date'):
        return result
    full = [event for event in events(result) if event.get('kind') in FULL]
    if len(full) != 1 or full[0].get('date') != second:
        return result
    source_url = record.get('detail_page') or record.get('funding_opportunity_url') or record.get('primary_document_url')
    event = {'kind': 'preproposal', 'stage': 'preproposal', 'date': first, 'required': True,
        'source': str(record.get('source') or 'Official source') + ' synopsis',
        'source_url': source_url, 'source_field': 'description', 'confidence': 'source_listed',
        'citation': {'source_field': 'description', 'quote': pair.group(), 'source_url': source_url},
        'requirement_citation': {'source_field': 'description', 'quote': obligations[0].group(), 'source_url': source_url}}
    event.update({key: full[0][key] for key in ('application_class', 'cycle', 'track') if key in full[0]})
    preliminary = [item for item in events(result) if item.get('kind') in PRELIMINARY]
    if any(item != event for item in preliminary):
        return result  # Conflicting or differently owned stages need source review.
    if not preliminary:
        result['deadlines'] = (result.get('deadlines') or []) + [event]
    result.update(has_preliminary_stage=True, preliminary_required=True, preliminary_stage_type='preproposal')
    return result


def project(record, as_of):
    result = project_two_step_prerequisite(project_invitation_access(record))
    result['next_submission'] = next_submission(result, as_of)
    return result
