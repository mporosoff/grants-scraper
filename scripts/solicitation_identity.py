"""Sponsor-scoped identities for DARPA and IARPA research solicitations."""

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
