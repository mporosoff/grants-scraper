"""Deterministic submission selection shared by catalog/feed/change consumers.

The browser/Worker implementation in assets/submission-schedule.js is checked
against these same fixtures. Selection does not alter source close_date or
infer applicant eligibility. It explains explicitly owned prerequisites.
"""
from copy import deepcopy
from datetime import date
import re

VERSION = 2
PRELIMINARY = {'letter_of_intent', 'concept_paper', 'white_paper', 'preapplication', 'preproposal'}
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
    result = [deepcopy(event) for event in (record.get('deadlines') or []) + (record.get('submission_requirements') or [])
              if isinstance(event, dict) and event.get('kind') in KINDS]
    if (not any(event.get('kind') in FULL | {'submission'} or event.get('date') == record.get('close_date') for event in result)
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


def project(record, as_of):
    result = deepcopy(record)
    result['next_submission'] = next_submission(record, as_of)
    return result
