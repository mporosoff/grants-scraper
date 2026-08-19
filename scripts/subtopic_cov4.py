"""Cov4 -- the two-axis publication gate for generically inferred subtopics.

**This module is an implementation of a frozen measurement, not a design.**
Everything it does was specified and measured before any of it was written:
`docs/MEAS3_RUN_DESIGN.md` sections 5a (the prompt experiment, 564 calls),
5d (the ownership experiment, seven real-document cases) and 5e (the decision),
with `tools/cov4_ownership.py` as the committed specification of the guard and
of the prompt. Nothing here is tuned. Two committed tests assert byte-equality
between the prompt and regex used below and the frozen ones, so a later edit to
either cannot drift silently.

**The invariant, stated once (`docs/MEAS3_RUN_DESIGN.md` 5d.2):**

> A candidate may be **semantically fundable and still invalid for this parent**
> if the evidence establishes it belongs to another opportunity. **Ownership and
> fundability are two axes**; a candidate must pass both, and one verdict must
> not silently combine them when ownership is deterministically decidable.

So this module answers **two** questions and keeps them apart:

1. :func:`determine_ownership` -- *does this span belong to this parent?* --
   decided **deterministically, with zero API calls**, from the ``source_kind``
   the pipeline already carries. Measured 42 of 43 candidates settled this way.
2. :func:`classify_fundability` -- *is this a fundable subdivision, or the
   announcement's furniture?* -- decided by the frozen two-axis prompt at
   `claude-sonnet-5`, **R=1** (licensed by MEAS-3's 0.190% pooled disagreement),
   over direct HTTP through the already-pinned ``requests``. No SDK, and no new
   dependency (DEC-15).

**Why ownership is not asked of the model.** The classifier *can* answer it --
O1 scored 2/2 on the cross-opportunity cases, 5/5 on re-test -- but it also
rejected one truly-owned span, and a deterministic guard cannot. A gate whose
false-rejection budget is zero takes the deterministic answer wherever one
exists (`docs/MEAS3_RUN_DESIGN.md` 5d.3).

**Why prose is not searched for foreign numbers on attachment-sourced spans.**
The over-aggression trap is real and is in the frozen evidence: a genuine HEP
programme quoted from page 96 of the parent's own notice cites its predecessor
`DE-FOA-0003354`, and an amended DOE notice repeats its own amendment history.
A rule of the form "a foreign number anywhere means reject" destroys both. The
guard never reads their prose at all, because Grants.gov already bound the
document to the record.

**Provenance boundary (section 18.1 Cov4, narrowed in 8.7).** Only `inline` and
`inferred` children enter this gate. `native` (NASA ROSES) and `referenced`
(Army TDAC) bypass it with **zero classifier calls**: Cov4 asks whether generic
inference found the fundable list or the announcement's furniture, and that
question does not arise when the agency published the list itself. A
disagreement there is a section 7.4 canary failure, not a filtering decision.

**Cov4 never upgrades provenance.** An approved `inferred` child stays
`inferred`; an approved `inline` child stays `inline`. The gate answers semantic
safety, and section 5.1's ceilings continue to bound confidence exactly as they
did before the gate existed.

**Fail-closed contract (section 18.1 Cov4, "the single most important line").**

> When the classifier is unavailable, unauthenticated, rate-limited, times out,
> or returns anything unparseable, the run publishes NOTHING NEW. It never falls
> back to publishing unfiltered spans.

Concretely: nothing in this module raises. An unresolved span is not a passing
span -- it is demoted to `low`, the tier that has never published, and it is
counted in the diagnostics so a build that could not reach the API is visible
rather than silent.
"""

from __future__ import annotations

import json
import os
import re

from scripts.subtopic_records import INFERRED, INLINE


# --- the provenance boundary -------------------------------------------------
#
# The only two rungs Cov4 judges. Membership is tested against the rung already
# written onto the record by `classify_provenance`, so the boundary is enforced
# on the value that ships rather than on a parallel notion of it.
CLASSIFIED_PROVENANCE = frozenset({INLINE, INFERRED})

# --- ownership outcomes ------------------------------------------------------
#
# Three, deliberately. `unestablished` is not a pass and not a conflict: the
# evidence is silent. Collapsing it into `owned` reopens BUG-9; collapsing it
# into `not_owned` rejects agency pages that simply do not print a number.
# `tools/cov4_ownership.py` names the middle outcome `conflict`; the production
# vocabulary says `not_owned`, which is the same verdict stated as what it does.
OWNED = "owned"
NOT_OWNED = "not_owned"
UNESTABLISHED = "unestablished"

#: Kinds whose documents Grants.gov itself attaches to the record. For these the
#: attachment binding *is* the ownership evidence, and prose is never consulted.
ATTACHMENT_KINDS = frozenset({"primary_notice", "secondary_attachment"})

#: Kinds fetched from an agency-hosted page, which may legitimately describe many
#: opportunities. Ownership must be corroborated for these.
AGENCY_KINDS = frozenset({"agency_notice", "subtopic_agency_notice"})

#: Solicitation-number shapes measured in this corpus. Deliberately narrow: each
#: is a real agency format seen in `data/opportunities.js`, not a general "looks
#: like an identifier" pattern. Byte-identical to the frozen specification, and
#: a committed test asserts that.
SOLICITATION_RE = re.compile(
    r"\bDE-FOA-\d{7}\b"                     # DOE
    r"|\bFA\d{4}-\d{2}-S-\d{4}\b"           # Air Force / AFOSR
    r"|\bW911NF-\d{2}-S-\d{4}\b"            # Army
    r"|\bN\d{5}\d*SB\d{3}\b"                # ONR
    r"|\bHR\d{6}S\d{4}\b"                   # DARPA
    r"|\bNNH\d{2}[A-Z]{3}\d{3}[A-Z]\b"      # NASA ROSES
    r"|\bHT\d{6}[A-Z]{2,}\d*\b",            # DHA / CDMRP
    re.IGNORECASE,
)

# --- fundability outcomes ----------------------------------------------------
ACCEPT = "accept"
REJECT = "reject"
UNRESOLVED = "unresolved"

# --- the frozen classifier configuration -------------------------------------
#
# Every value here was fixed by the committed experiment and none of it is a
# knob. R=1 is licensed by MEAS-3's decision table (the "one pass, no ensemble"
# branch, taken on a pooled 0.190% disagreement). `thinking` is deliberately
# absent rather than disabled -- omitting the parameter is the measured
# difference between 88% and 54% span-level precision (section 11) -- and every
# other parameter stays at the API default.
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024
TIMEOUT_SECONDS = 120
REPEATS = 1
API_KEY_ENV = "ANTHROPIC_API_KEY"

#: The O1 two-axis prompt, selected by the ownership experiment and frozen in
#: `tools/cov4_ownership.py`. **Do not tune it.** A test asserts byte-equality
#: with the frozen copy; if this string is edited the test fails, which is the
#: point.
PROMPT = """\
You are judging one candidate heading extracted from a US federal funding notice, on
behalf of ONE specific parent opportunity.

PARENT OPPORTUNITY
  number: {parent_number}
  title:  {parent_title}

WHERE THIS CANDIDATE CAME FROM
  document: {source_document_name}
  location: {source_document_url}

CANDIDATE
  label:   {code}
  title:   {title}
  excerpt:
\"\"\"
{excerpt}
\"\"\"

Answer TWO questions about this candidate.

1. **Ownership.** Does this candidate belong to the parent opportunity named above?
   Answer "no" if the evidence shows it belongs to a *different* funding opportunity —
   for example a page or document that lists several opportunities and attributes this
   item to another one. A passing mention of another solicitation *inside* the
   parent's own material — a predecessor programme, an amendment history, a
   cross-reference — does **not** make it someone else's.

2. **Fundability.** Could an applicant propose research work against this candidate
   within the parent opportunity — a named programme, topic, research area, challenge
   area or technical category? A descriptive paragraph about the science is the normal
   form of a real programme, not evidence against one. Answer "no" for application
   contents, submission or reporting requirements, review criteria, eligibility or
   teaming rules, general policy, navigation or table-of-contents text, placeholders,
   or the awarding agency, office or division itself.

Answer with a single JSON object and nothing else:
{{"owned": "yes" | "no", "fundable": "yes" | "no", "reason": "<one short sentence>"}}"""

#: Excerpt truncation, frozen with the prompt.
MAX_EXCERPT_CHARS = 4000


# --- axis 1: ownership, deterministic ---------------------------------------

def normalise_number(value) -> str:
    """Upper-cased alphanumerics only, so `DE-FOA-0003215` == `defoa0003215`."""
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def solicitation_numbers(*texts) -> set:
    """Every measured solicitation-number shape appearing in the given texts."""
    found = set()
    for text in texts:
        for match in SOLICITATION_RE.finditer(str(text or "")):
            found.add(normalise_number(match.group(0)))
    return found


def determine_ownership(candidate) -> dict:
    """Does this span belong to this parent? Deterministic, and no API call.

    The frozen rule (`tools/cov4_ownership.py`, strategy O2), in order:

    1. **Attachment provenance wins outright.** If the span's source document is
       a Grants.gov attachment of this record (`primary_notice` /
       `secondary_attachment`), the candidate is **owned** and *no prose is
       examined*. This is what protects amendment histories, predecessor
       references and ordinary cross-references from being read as conflicts.
    2. Otherwise the source is an agency-hosted page, and ownership must be
       shown:
       a. the parent's own number appears in the document identity or the span
          text -> **owned**;
       b. else some *other* measured solicitation number appears ->
          **not_owned**;
       c. else -> **unestablished** (not a conflict, and not a pass).
    3. An unrecognised or missing `source_kind` is **unestablished**, never
       owned. An old cache entry that predates `source_kind` must fail closed.

    Returns a diagnostic dict. `consulted_prose` records whether rule 1 applied,
    because "did the guard read the text at all" is what the over-aggression
    trap turns on.
    """
    kind = (candidate.get("source_kind") or "").strip()
    parent = normalise_number(candidate.get("parent_opportunity_number"))
    if kind in ATTACHMENT_KINDS:
        return {
            "ownership": OWNED,
            "basis": "grants_gov_attachment_binding",
            "source_kind": kind,
            "consulted_prose": False,
        }
    if kind not in AGENCY_KINDS:
        return {
            "ownership": UNESTABLISHED,
            "basis": "unknown_source_kind",
            "source_kind": kind,
            "consulted_prose": False,
        }
    found = solicitation_numbers(
        candidate.get("source_document_name"),
        candidate.get("source_document_url"),
        candidate.get("excerpt"),
        candidate.get("title"),
    )
    if parent and parent in found:
        return {
            "ownership": OWNED,
            "basis": "agency_page_names_parent",
            "source_kind": kind,
            "consulted_prose": True,
        }
    if {number for number in found if number != parent}:
        return {
            "ownership": NOT_OWNED,
            "basis": "agency_page_names_only_other_opportunities",
            "source_kind": kind,
            "consulted_prose": True,
        }
    return {
        "ownership": UNESTABLISHED,
        "basis": "agency_page_names_no_opportunity",
        "source_kind": kind,
        "consulted_prose": True,
    }


# --- axis 2: fundability, semantic ------------------------------------------

def render_prompt(candidate) -> str:
    """The frozen prompt for one candidate. Pure, and makes no request."""
    return PROMPT.format(
        parent_number=candidate.get("parent_opportunity_number") or "(not stated)",
        parent_title=candidate.get("parent_title") or "",
        source_document_name=candidate.get("source_document_name") or "(not stated)",
        source_document_url=candidate.get("source_document_url") or "(not stated)",
        code=candidate.get("subtopic_code") or "",
        title=candidate.get("title") or "",
        excerpt=(candidate.get("excerpt") or "")[:MAX_EXCERPT_CHARS],
    )


def _unresolved(error, *, detail=None):
    """The one shape every failure takes. Never carries a credential."""
    return {
        "fundability": UNRESOLVED,
        "classifier_owned": None,
        "reason": None,
        "error": error,
        "detail": detail,
    }


def classify_fundability(candidate, *, api_key=None, session=None):
    """Ask the frozen prompt about one candidate. Never raises.

    Returns ``{"fundability", "classifier_owned", "reason", "error", "detail"}``.
    `classifier_owned` is the model's *opinion* on the ownership axis. It is
    recorded for diagnostics and for the review queue and it **never** decides
    publication -- :func:`determine_ownership` does, deterministically.

    Every failure mode named in the fail-closed contract lands on `unresolved`:
    a missing credential, a timeout, a non-2xx response, malformed JSON, an
    unparseable body, and an answer outside the frozen enum. None of them is a
    pass, and none of them raises into the caller's build.

    `session` is injected by the caller so one connection is reused across a
    document's spans, and so tests drive this without a network.
    """
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        # Not an error worth a stack trace: an unauthenticated build is a build
        # that adds no subtopics, which is the specified outcome.
        return _unresolved("missing_credential")

    try:
        import requests
    except Exception:                       # noqa: BLE001 - pinned, never fatal
        return _unresolved("requests_unavailable")

    client = session if session is not None else requests
    try:
        response = client.post(
            API_URL,
            headers={
                "x-api-key": key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                # `thinking` deliberately omitted -- see the configuration note.
                "messages": [
                    {"role": "user", "content": render_prompt(candidate)}
                ],
            },
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:                # noqa: BLE001 - network, DNS, timeout
        # The exception *type* is a useful diagnostic; its message can quote the
        # request that carried the key, so it is deliberately not recorded.
        return _unresolved("request_failed", detail=type(exc).__name__)

    status = getattr(response, "status_code", None)
    if status != 200:
        return _unresolved("http_error", detail=f"status_{status}")

    try:
        payload = response.json()
        text = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        ).strip()
    except Exception:                       # noqa: BLE001 - malformed body
        return _unresolved("malformed_response")

    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
    except Exception:                       # noqa: BLE001 - no JSON object in it
        return _unresolved("unparseable_response")
    if not isinstance(parsed, dict):
        return _unresolved("unparseable_response")

    fundable = str(parsed.get("fundable", "")).strip().lower()
    owned = str(parsed.get("owned", "")).strip().lower()
    if fundable not in {"yes", "no"}:
        return _unresolved("unexpected_enum", detail=f"fundable={fundable[:20]!r}")
    return {
        "fundability": ACCEPT if fundable == "yes" else REJECT,
        "classifier_owned": {"yes": True, "no": False}.get(owned),
        "reason": str(parsed.get("reason", ""))[:300] or None,
        "error": None,
        "detail": None,
    }


# --- the gate ----------------------------------------------------------------

def candidate_from_record(parent, record, document):
    """The Cov4 input for one built section 5.1 record.

    Everything the frozen specification names is already on the record or on the
    document the segmenter chose -- parent record id, parent opportunity number,
    parent title, source URL/name/hash, `source_kind`, candidate title, excerpt
    and provenance. **No second candidate pipeline**: this is a projection of
    what `build_records` already produced, not a re-derivation of it.
    """
    document = document or {}
    return {
        "parent_record_id": record.get("parent_id"),
        "parent_opportunity_number": record.get("parent_opportunity_number"),
        "parent_title": (parent or {}).get("title"),
        "source_kind": document.get("source_kind"),
        "source_document_name": document.get("name"),
        "source_document_url": (
            record.get("source_document_url") or document.get("url")
        ),
        "source_document_hash": (
            record.get("source_document_hash") or document.get("sha256")
        ),
        "subtopic_code": record.get("subtopic_code"),
        "title": record.get("title"),
        "excerpt": record.get("summary"),
        "provenance": record.get("subtopic_source"),
        "subtopic_id": record.get("subtopic_id"),
    }


def _counter(mapping, key):
    mapping[key] = mapping.get(key, 0) + 1


def apply_gate(parent, records, document, *, classifier=None, api_key=None,
               session=None):
    """Filter one parent's built records through both axes. Never raises.

    Returns ``(kept, diagnostics)``.

    * A record whose `subtopic_source` is not `inline` or `inferred` is returned
      **untouched and unannotated**, and no classifier call is made for it. That
      is the P6 bypass, enforced here rather than asserted elsewhere.
    * A rejection on either axis -- a cross-opportunity child, or a span the
      classifier rejects -- is **dropped and counted**. A dropped span is not
      queued: it is either someone else's child or the announcement's furniture,
      and neither belongs in this parent's cache.
    * Everything else that did not pass -- `unestablished` ownership, an
      abstention, a malformed answer, an API failure, a missing credential -- is
      **retained and demoted to `low`**, the tier that has never published, and
      flagged for review. That is the fail-closed path, and it is why an outage
      costs recall rather than correctness.

    Both axes are evaluated independently for every candidate that enters, so
    the diagnostics can say *which* axis rejected a span. A fundable child of the
    wrong parent is still rejected, and the diagnostics still show it as
    fundable.
    """
    classify = classifier if classifier is not None else classify_fundability
    diagnostics = {
        "model": MODEL,
        "repeats": REPEATS,
        "offered": 0,
        "bypassed": 0,
        "bypassed_provenance": {},
        "ownership": {},
        "fundability": {},
        "published": 0,
        "dropped": 0,
        "review": 0,
        "classifier_calls": 0,
        "classifier_errors": {},
    }
    kept = []
    for record in records or []:
        rung = record.get("subtopic_source")
        if rung not in CLASSIFIED_PROVENANCE:
            diagnostics["bypassed"] += 1
            _counter(diagnostics["bypassed_provenance"], str(rung))
            kept.append(record)
            continue

        diagnostics["offered"] += 1
        candidate = candidate_from_record(parent, record, document)

        ownership = determine_ownership(candidate)
        _counter(diagnostics["ownership"], ownership["ownership"])

        verdict = classify(candidate, api_key=api_key, session=session)
        diagnostics["classifier_calls"] += 1
        _counter(diagnostics["fundability"], verdict["fundability"])
        if verdict.get("error"):
            _counter(diagnostics["classifier_errors"], verdict["error"])

        annotated = dict(record)
        # Provenance is NOT touched here, ever. Cov4 answers semantic safety;
        # the rung records who asserted the parent->child relationship, and no
        # classifier verdict can change who asserted it (section 5.1).
        annotated["cov4_ownership"] = ownership["ownership"]
        annotated["cov4_ownership_basis"] = ownership["basis"]
        annotated["cov4_fundability"] = verdict["fundability"]

        if ownership["ownership"] == NOT_OWNED or verdict["fundability"] == REJECT:
            diagnostics["dropped"] += 1
            continue
        if ownership["ownership"] != OWNED or verdict["fundability"] != ACCEPT:
            annotated["cov4_review"] = True
            # `low` is the existing never-publishes tier (section 13, and the
            # same demotion `subtopic_sources._demote` already applies). No new
            # publication state is invented to express "queued".
            annotated["confidence"] = "low"
            diagnostics["review"] += 1
            kept.append(annotated)
            continue
        diagnostics["published"] += 1
        kept.append(annotated)

    return kept, diagnostics
