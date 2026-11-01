"""Conservative project durations from locally owned notice fields."""
import re

VERSION = 'duration-scope-1'
_DURATION = re.compile(
    r'\b(?:period\s+of\s+performance|project\s+(?:period|duration)|'
    r'award\s+(?:period|duration))\D{0,90}?'
    r'(?P<amount>\d{1,3})(?P<range>\s*[-\u2013\u2014]\s*\d{1,3}|\s+to\s+\d{1,3})?\s*'
    r'(?P<unit>months?|years?)\b', re.I)
_TRACK_DECLARATION = re.compile(
    r'\b(?:Topic\s+Area|Track)\s+(?:\d+|[A-Z])\s*[:\u2013\u2014-]', re.I)
_MAXIMUM = re.compile(r'\b(?:up\s+to|not\s+(?:to\s+)?exceed|maximum)\b', re.I)


def _months(amount, unit):
    return int(amount) * (12 if unit.casefold().startswith('year') else 1)


def _scoped(text, match):
    """An explicit local declaration, including unresolved clipped ownership."""
    declarations = list(_TRACK_DECLARATION.finditer(text))
    if any(owner.end() <= match.start() for owner in declarations):
        # Full structures use funding_track's section boundary below. This
        # local check also recognizes the NSF inline "Track 1 - ..." field.
        owner = next(owner for owner in reversed(declarations) if owner.end() <= match.start())
        if not re.search(r'(?m)^\s*\d+\.\s+[A-Z]', text[owner.end():match.start()]):
            return True
    # A clipped funding-list quote ending at the next topic cannot establish
    # its missing owner. It proves neither Topic 1 nor any other topic's value.
    return (text.lstrip().startswith(('\u2026', '...'))
            and bool(re.search(r'\bApproximate\s+award\s+project\s+period\b', text, re.I))
            and any(owner.start() >= match.end() for owner in declarations))


def unscoped_duration(fact):
    """Whether this retained scalar visibly omits its local topic ownership.

    The caller must first verify the citation's document URL and hash. Only
    the fact's own quoted value is considered; no absent values are invented.
    """
    if fact.get('type') != 'project_duration' or fact.get('track'):
        return False
    value = fact.get('value')
    if not isinstance(value, dict) or not isinstance(value.get('amount'), int):
        return False
    if value.get('unit') not in {'month', 'months', 'year', 'years'}:
        return False
    quote = (fact.get('citation') or {}).get('quote') or ''
    return any(_months(match['amount'], match['unit']) == _months(value['amount'], value['unit'])
               and _scoped(quote, match) for match in _DURATION.finditer(quote))


def facts(api, opportunity_id, containers, document, extracted_at):
    """Keep a scalar only when retained fields support one unscoped duration."""
    from scripts import notice_semantics

    matches = []
    for container in containers:
        text = container['text']
        for begin, end in notice_semantics.substantive_spans(container):
            for match in _DURATION.finditer(text, begin, end):
                if (match['range'] or notice_semantics.funding_track(container, match.start())
                        or _scoped(text, match)):
                    return []
                matches.append((container, match))
    if not matches or len({_months(match['amount'], match['unit']) for _, match in matches}) != 1:
        return []
    container, match = matches[0]
    value = {'amount': int(match['amount']), 'unit': match['unit'].casefold()}
    # Maximum immediately before the field label belongs to that field; a
    # maximum award amount elsewhere in the paragraph does not.
    prefix = container['text'][max(0, match.start() - 12):match.start()]
    maximum = bool(_MAXIMUM.search(match.group()) or re.search(r'\bmaximum\s*$', prefix, re.I))
    display = f"{'Up to ' if maximum else ''}{value['amount']} {value['unit']}"
    return [api.make_fact(opportunity_id, 'project_duration', 'Project duration', value, display,
                          api.citation_for(container, document, match.start(), match.end(), extracted_at),
                          parser_version=VERSION)]
