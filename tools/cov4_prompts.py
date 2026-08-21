"""Pre-registered Cov4 prompt variants. Committed before any variant was run.

**Why this file exists.** MEAS-3 measured *repeatability* and found it good (R=1
licensed). What it exposed instead was a **task-definition** failure: four genuine
DOE/Genesis programmes were rejected **stably**, five times out of five, and every
rejection reason repeated the same two moves —

    "This is descriptive background on a research area …"
    "… not a distinct fundable subdivision applicants select against."

The MEAS-3 prompt asks whether a candidate is *"something an applicant would actually
apply against or **select**"*. The model reads **select** as requiring a formal
application category, and reads a prose programme description as *background*. In a
DOE omnibus every genuine programme is exactly that: a prose description of a research
area you propose work against. So the prompt's decision rule, not the model, is what
rejects them.

The model states the correct rule itself in the single accepting run of the one
unstable span: *"Names a specific research program area (X-Ray Scattering) under BES
that applicants can propose research against."*

**Design rules honoured here:**

* variants differ **only** in the semantic decision rule — model, sampling, input
  fields and output schema are identical;
* **no variant names or special-cases any of the failed titles**, or any other
  candidate; they state general criteria only;
* `V0` is the **unmodified MEAS-3 prompt**, carried as a control so both populations
  have a baseline. Carrying it is not a correction to MEAS-3, whose result stands.
"""

from __future__ import annotations

#: Identical across every variant: the same fields in the same order, and the same
#: output schema. Only the rule between them changes.
_HEADER = """\
You are judging one candidate heading extracted from a US federal funding notice.

Parent opportunity: {parent_title}
Parent number: {parent_number}

Candidate label: {code}
Candidate title: {title}
Candidate excerpt:
\"\"\"
{excerpt}
\"\"\"
"""

_SCHEMA = """
Answer with a single JSON object and nothing else:
{{"verdict": "accept" | "reject", "reason": "<one short sentence>"}}"""


#: V0 — the MEAS-3 prompt, verbatim. Control arm.
V0_CONTROL = """\
You are judging one candidate heading extracted from a US federal funding notice.

The question is narrow: **is this candidate a fundable subdivision of the parent \
opportunity — something an applicant would actually apply against or select — \
rather than policy text, organizational structure, navigation, background material, \
eligibility prose, administrative sections or another non-fundable heading?**

Parent opportunity: {parent_title}
Parent number: {parent_number}

Candidate label: {code}
Candidate title: {title}
Candidate excerpt:
\"\"\"
{excerpt}
\"\"\"

Answer with a single JSON object and nothing else:
{{"verdict": "accept" | "reject", "reason": "<one short sentence>"}}

Use "accept" only if it is a fundable subdivision an applicant selects. \
Use "reject" for anything administrative, procedural, organizational, or belonging \
to another opportunity. If the excerpt is too corrupted or truncated to judge the \
titled subject, say so in the reason and answer "reject"."""


#: V1 — "propose against". Replaces formal selectability with the project's actual
#: definition, and says explicitly that a prose description of a research area is
#: the normal form of a genuine programme rather than evidence against one.
V1_PROPOSE_AGAINST = _HEADER + """
Decide whether this candidate is a **research subdivision of the parent opportunity \
that an applicant could propose work against** — a named programme, topic, research \
area, challenge area or technical category the umbrella funds.

It does **not** need to be a formally selectable application category, a checkbox, or \
a separate submission route. Many genuine subdivisions are presented simply as a \
named research area with a prose description of its scope; **a descriptive paragraph \
about the science is the normal form of a real programme, not evidence against one.**

Answer "reject" only when the candidate is not a research subject at all — for \
example application instructions, submission or reporting requirements, review \
criteria, eligibility or teaming rules, general policy, the awarding organization or \
one of its offices/divisions, table-of-contents or navigation text, a placeholder, or \
a heading that belongs to a different funding opportunity.
""" + _SCHEMA


#: V2 — "subject vs process", with an explicit granularity rule. Same broadened
#: notion of fundability, but framed as a two-way sort and with the office/division
#: level called out as too coarse, which is the hardest negative in the set.
V2_SUBJECT_VS_PROCESS = _HEADER + """
Sort this candidate into one of two kinds.

**A research subject** — a named programme, topic, research area, challenge area or \
technical category *within* the parent opportunity, which an applicant could write a \
proposal about. Accept these. A subject stays a subject whether it is described in one \
line or several paragraphs of scientific prose, and whether or not the notice gives it \
a formal selection mechanism.

**A process or container** — anything about *how* to apply, *who* may apply, *how it \
will be reviewed*, *what must be reported*, or *who is running the programme*: \
application contents, attachments, submission or reporting rules, review criteria, \
eligibility and teaming requirements, policy statements, navigation and \
table-of-contents entries, placeholders, and the awarding agency, office or division \
itself. Reject these.

Two boundary rules:

* **Granularity.** The whole agency, a programme office, or a division that *contains* \
the research subdivisions is too coarse — reject it; the fundable unit is the named \
subject beneath it.
* **Ownership.** If the candidate belongs to a different funding opportunity than the \
parent named above, reject it however research-like it looks.
""" + _SCHEMA


#: V3 — V2's rule plus one explicit tie-break for the case the diagnosis showed is
#: decisive: prose description of a named area. Stated as a general principle, not
#: as an instance.
V3_SUBJECT_WITH_TIEBREAK = _HEADER + """
Decide whether an applicant could propose research work **against this candidate**, \
within the parent opportunity.

Accept a named programme, topic, research area, challenge area or technical category \
that the umbrella funds.

Reject anything that is not a research subject: application contents or attachments, \
submission, budget or reporting requirements, review criteria, eligibility or teaming \
rules, general policy, navigation or table-of-contents text, placeholders, the \
awarding agency or one of its offices or divisions, and anything belonging to a \
different opportunity.

When you are unsure, apply these tie-breaks in order:

1. **Would a proposal's subject line plausibly cite this?** If yes, accept.
2. **Does the text describe a field of study, or a procedure?** A field of study is a \
subject even when written as background prose; a procedure is not, even when written \
about science.
3. **Is it the container or the contents?** Offices and divisions are containers; \
reject. The named areas inside them are contents; accept.
""" + _SCHEMA


#: The pre-registered set. Order is the run order.
VARIANTS = {
    "V0_control": V0_CONTROL,
    "V1_propose_against": V1_PROPOSE_AGAINST,
    "V2_subject_vs_process": V2_SUBJECT_VS_PROCESS,
    "V3_subject_with_tiebreak": V3_SUBJECT_WITH_TIEBREAK,
}


def render(variant: str, candidate: dict) -> str:
    """Fill one variant with a candidate's fields. Identical fields for every variant."""
    return VARIANTS[variant].format(
        parent_title=candidate.get("parent_title") or "",
        parent_number=candidate.get("parent_opportunity_number") or "",
        code=candidate.get("subtopic_code") or "",
        title=candidate.get("title") or "",
        excerpt=(candidate.get("excerpt") or "")[:4000],
    )
