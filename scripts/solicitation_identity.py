"""Sponsor-scoped solicitation keys, independent of stable public record IDs."""

import re
import unicodedata


def normalized_number(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def research_sponsor(record):
    # Use sponsor fields, never title/description or a host shared by agencies.
    text = " ".join(str(record.get(key) or "") for key in ("agency", "agency_code"))
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    if re.search(r"\biarpa\b|\bintelligence advanced research projects activity\b", text):
        return "iarpa"
    if re.search(r"\bdarpa\b|\bdefense advanced research projects agency\b", text):
        return "darpa"
    return None


def research_solicitation_key(record):
    sponsor = research_sponsor(record)
    number = normalized_number(record.get("opportunity_number"))
    return (sponsor, number) if sponsor and number else None


SPONSOR_ALIASES = {
    'nsf': r'\b(?:nsf|national science foundation)\b',
    'nasa': r'\b(?:nasa|national aeronautics and space administration)\b',
    'doe': r'\b(?:doe|department of energy|arpa e|eere|office of science)\b',
    'nih': r'\b(?:nih|national institutes? of health)\b',
    'cdc': r'\b(?:cdc|centers? for disease control(?: and prevention)?)\b',
    'fda': r'\b(?:fda|food and drug administration)\b',
    'onr': r'\b(?:onr|office of naval research)\b',
    'afosr': r'\b(?:afosr|air force office of scientific research)\b',
    'usda': r'\b(?:usda|department of agriculture)\b',
    'epa': r'\b(?:epa|environmental protection agency)\b',
    'nyserda': r'\b(?:nyserda|new york state energy research and development authority)\b',
}


def sponsor_identity(record):
    if record.get('agency_authority') == 'source_default':
        # Recognizable spelling cannot elevate an aggregator's default.
        return None
    research = research_sponsor(record)
    if research:
        return research
    # No title, solicitation-number prefix, description, or shared web host
    # may manufacture a sponsor. Conflicting sponsor fields remain unresolved.
    agency = re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKC', str(record.get('agency') or '')).casefold()).strip()
    code = re.sub(r'[^a-z0-9]+', ' ', str(record.get('agency_code') or '').casefold()).strip()
    identities = {key for key, pattern in SPONSOR_ALIASES.items() if re.search(pattern, agency + ' ' + code)}
    if len(identities) == 1:
        return identities.pop()
    if identities:
        return None
    if not agency or agency in {'unknown', 'other', 'federal', 'multiple', 'various', 'unspecified'}:
        return None
    if record.get('agency_authority') == 'source_default':
        # A digest/aggregator default is not an authoritative funding agency.
        return None
    return 'agency:' + agency


def solicitation_key(record):
    sponsor = sponsor_identity(record)
    number = normalized_number(record.get('opportunity_number'))
    if sponsor == 'nsf':
        number = re.sub(r'^nsf(?=\d{5,}$)', '', number)
    return (sponsor, number) if sponsor and number else None
