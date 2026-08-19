"""Pre-registered Cov4 ownership strategies O1/O2/O3. Committed before any run.

**The blocker this addresses.** The prompt experiment (2026-08-25) solved recall —
V1/V3 keep 100% of known genuine children — but **all four variants accepted a topic
belonging to a different opportunity**, which is BUG-9's fabrication surface. Two of
those variants stated an ownership rule in words and supplied the parent number, and
it made no difference.

**The ownership invariant** (§2 of the session brief), stated once:

> A candidate may be **semantically fundable and still invalid for this parent** if
> the evidence establishes it belongs to another opportunity. Ownership and
> fundability are **two axes**, and a candidate must pass both. Cov4 must not ask one
> verdict to silently combine them when ownership is deterministically decidable.

**The production inventory that makes this tractable.** Traced through
`source_for_record`, `subtopic_sources` and `build_records`: exactly four document
kinds reach segmentation, and two of them carry an ownership guarantee *by
construction*.

| `source_kind` | Origin | Ownership |
|---|---|---|
| `primary_notice` | a Grants.gov attachment of this record | **bound by Grants.gov** |
| `secondary_attachment` | §6.6's multi-attachment path, also a Grants.gov attachment | **bound by Grants.gov** |
| `agency_notice` | the record's own agency URL | **not guaranteed** |
| `subtopic_agency_notice` | Cov1's `subtopic_only_primary`, the agency URL for records Grants.gov declines | **not guaranteed — this is BUG-9's path** |

So ownership is answered by **source-level provenance**, not by reading prose — which
is what §5 of the brief asks for, and what keeps the guard away from amendment
histories and cross-references.
"""

from __future__ import annotations

import re

#: Kinds whose documents Grants.gov itself attaches to the record. For these the
#: attachment binding *is* the ownership evidence, and prose is never consulted.
ATTACHMENT_KINDS = frozenset({"primary_notice", "secondary_attachment"})

#: Kinds fetched from an agency-hosted page, which may legitimately describe many
#: opportunities. Ownership must be corroborated for these.
AGENCY_KINDS = frozenset({"agency_notice", "subtopic_agency_notice"})

#: Solicitation-number shapes measured in this corpus. Deliberately narrow: each is a
#: real agency format seen in `data/opportunities.js`, not a general "looks like an
#: identifier" pattern.
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

OWNED = "owned"
CONFLICT = "conflict"
UNESTABLISHED = "unestablished"


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


def ownership_o2(candidate) -> dict:
    """**O2 — deterministic guard, source-level first.**

    Pre-registered rule, in order:

    1. **Attachment provenance wins outright.** If the span's source document is a
       Grants.gov attachment of this record (`primary_notice` /
       `secondary_attachment`), the candidate is **owned**, and *no prose is
       examined*. This is what protects amendment histories, predecessor references
       and cross-references from being read as ownership conflicts.
    2. Otherwise the source is an agency-hosted page, and ownership must be shown:
       a. the parent's own number appears in the document identity or the excerpt →
          **owned**;
       b. else some *other* measured solicitation number appears → **conflict**;
       c. else → **unestablished** (not a conflict, and not a pass).

    `unestablished` is deliberately its own outcome. Treating it as a pass would
    reopen BUG-9; treating it as a conflict would reject agency pages that simply do
    not print a number.
    """
    kind = (candidate.get("source_kind") or "").strip()
    parent = normalise_number(candidate.get("parent_opportunity_number"))
    if kind in ATTACHMENT_KINDS:
        return {"ownership": OWNED, "basis": "grants_gov_attachment_binding",
                "kind": kind, "consulted_prose": False}
    if kind not in AGENCY_KINDS:
        return {"ownership": UNESTABLISHED, "basis": f"unknown_source_kind:{kind!r}",
                "kind": kind, "consulted_prose": False}
    found = solicitation_numbers(
        candidate.get("source_document_name"),
        candidate.get("source_document_url"),
        candidate.get("excerpt"),
        candidate.get("title"),
    )
    if parent and parent in found:
        return {"ownership": OWNED, "basis": "agency_page_names_parent",
                "kind": kind, "consulted_prose": True, "numbers": sorted(found)}
    foreign = {n for n in found if n != parent}
    if foreign:
        return {"ownership": CONFLICT, "basis": "agency_page_names_only_other_opportunities",
                "kind": kind, "consulted_prose": True, "numbers": sorted(found)}
    return {"ownership": UNESTABLISHED, "basis": "agency_page_names_no_opportunity",
            "kind": kind, "consulted_prose": True, "numbers": sorted(found)}


#: **O1 — classifier context only.** Parent identity and source identity are supplied
#: explicitly and the model is asked to decide ownership itself. This is the arm that
#: tests whether the previous failure was under-instruction or missing evidence.
O1_PROMPT = """\
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


def render_o1(candidate) -> str:
    return O1_PROMPT.format(
        parent_number=candidate.get("parent_opportunity_number") or "(not stated)",
        parent_title=candidate.get("parent_title") or "",
        source_document_name=candidate.get("source_document_name") or "(not stated)",
        source_document_url=candidate.get("source_document_url") or "(not stated)",
        code=candidate.get("subtopic_code") or "",
        title=candidate.get("title") or "",
        excerpt=(candidate.get("excerpt") or "")[:4000],
    )


def strategy_o3(candidate, classifier_owned=None) -> dict:
    """**O3 — deterministic guard first, classifier context only for the residue.**

    The guard decides `owned` and `conflict`. Only `unestablished` is handed to the
    classifier, and only its *ownership* answer is consulted; fundability is judged by
    the semantic prompt either way.
    """
    guard = ownership_o2(candidate)
    if guard["ownership"] in {OWNED, CONFLICT}:
        return dict(guard, strategy="O3", decided_by="guard")
    if classifier_owned is None:
        return dict(guard, strategy="O3", decided_by="guard_unresolved")
    return {
        "ownership": OWNED if classifier_owned else CONFLICT,
        "basis": "classifier_resolved_unestablished",
        "kind": guard["kind"],
        "consulted_prose": True,
        "strategy": "O3",
        "decided_by": "classifier",
    }


#: **Pre-registered expectations**, written before the run so the result can falsify
#: them rather than be narrated around:
#:
#: * **O1** is expected to *fail* the aggregating-page case. The four variants already
#:   received `Parent number:` and still accepted it, so supplying identity alone is
#:   unlikely to be the missing ingredient — though O1 states the rule far more
#:   explicitly, so it may succeed.
#: * **O2** is expected to reject the aggregating-page case and to pass every
#:   attachment-sourced candidate, including the predecessor citation and the
#:   amendment history, because it never reads their prose.
#: * **O3** is expected to equal O2 on this challenge set, differing only where a
#:   candidate is `unestablished`.
EXPECTATIONS = {
    "O1": "fails the aggregating-page case (identity alone was already supplied)",
    "O2": "rejects aggregating page; passes all attachment-sourced candidates",
    "O3": "equals O2 here; differs only on unestablished candidates",
}
