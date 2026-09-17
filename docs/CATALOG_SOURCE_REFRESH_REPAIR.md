# September 15 catalog source repair

The public catalog is September 11 data. September 14's candidate (PR249,
`f56721d3e6bd4db720604414994614aa471b4d250b241f6e05dcc10fb1b76673`)
failed publication and subsequently received two consequential source findings.
September 15's scheduled run34985535113 generated another candidate
`ebbfe144a0978a1807c899856e84d426237f458e36250d1653632ee67ae0d0ba`
(PR253), retaining those source errors. It stopped before any serving change:
the Actions bot's review request was declined by the connector, then the
publication review wait expired. Generation succeeded; public publication did not.

This repair recognizes the sponsor on the official NSF feed's own HTTPS funding
links. Previously the adapter omitted the agency, so canonicalization marked
NSF as an aggregator default and the correct sponsor-scoped duplicate guard
could not join its rows to Grants.gov. The existing merger continues to keep
the Grants.gov identity and facts, preserve the alternate official links as
source aliases, and record conflicting facts rather than override them.
Program description identifiers retain `PD` and their full suffix; different
solicitation editions remain distinct. Generic RSS feeds gain no sponsor authority.

VPR applicant-directed prose can no longer open an opportunity buffer, including
a sentence that ends with a link lead-in rather than a full stop. It remains
inside the preceding call so its deadline does not move into a fictitious card.
The existing publication filter also rejects a previously cached VPR fragment,
including `vpr-email:vpr-7921302c954613de`.

The confirmed source equivalences are Grants.gov350802 / NSF24-503 and
Grants.gov334326 / NSF21-595. Their official program pages identify the same
guidelines: [RET](https://www.nsf.gov/funding/opportunities/research-experiences-teachers-engineering-computer-science)
and [TCUP](https://www.nsf.gov/funding/opportunities/tcup-tribal-colleges-universities-program).
The real NSF feed was retrieved once at 2026-09-15T15:52:37.692120Z:
11,697 bytes, SHA256`ad9f19176c2d9c3fd6b9c0b7fd3910cbfb8ee5599e5d8baceae0f139733fbcdc`,
12 entries; all 12 now have the feed's authoritative sponsor and complete number.

Other repeated-number records are audited separately. A VPR heading, number or
generic agency link alone is not silently promoted to verified sponsor identity.
Those unresolved source comparisons must remain visible in the release report;
they are not proof that every repeated number is a duplicate. No similarity-based
collapse, source-date invention or researcher/team requalification is introduced.

Validation: 95 focused source/parser/lifecycle tests pass, including exact IDs,
retained evidence/conflicts, idempotence, program-code/successor separation,
untrusted URLs, HTML/plain digest segmentation and cached-fragment filtering.
Required exact-head CI and independent review remain publication gates. No
E2E/Playwright run is required or initiated by this source-only repair.

Publication must use a corrected, preserved candidate through the existing
immutable release lifecycle. Neither held candidate is silently modified or
approved. A connected maintainer must initiate the actual candidate's review:
the current Actions bot has no working Codex connection. Do not reuse researcher
publication credentials for catalog review, bypass review, or represent a
successful source build as a public update. Researcher registry activation and
the contextual/Luna scientific checker are separate boundaries.


## September 17 continuation: canonical deadlines and durable review waiting

The owner resumed the deadline repair and publication after PR #257's completed
review identified a duplicate YIP card. The canonical Grants.gov record 363829
already preserves the October 9 white-paper prerequisite and December 4
application deadline. The VPR copy incorrectly exposed October 9 as a stand-alone
application. The fix joins the copy using its official record identity and
retains the conflicting digest date as evidence; it does not change the deadline
parser or infer identity from a title.

The official Simpler page's labelled Grants.gov/version-history links establish
its numeric legacy identity. Only exact HTTPS Grants.gov record paths and exact
Simpler opportunity UUIDs are accepted. Redirects to another identity, ambiguous
links and conflicting sponsor/solicitation facts fail closed. At most 20 distinct
missing mappings are fetched per source refresh through the existing public
HTTP client. Cache receipts preserve the original retrieval time, URL, UTF-8
content hash and locator. No researcher or provider endpoint is involved.

Official YIP evidence was retrieved at 2026-09-17T19:48:08.120841+00:00 from
https://simpler.grants.gov/opportunity/c342c01d-4f34-440f-8bb2-4bdd4d763df0
(281,053 UTF-8 bytes; SHA-256
`2b9d99f7f2f6e4a94fe7836d52911b52ed8c2a1c7e1abf0804d855a2028124a5`).
The source-only audit also establishes native aliases for 363632, 363378 and 363745.
Replaying the retained September 17 candidate against these identities reduces
1,395 records to 1,391, preserving the canonical YIP prerequisite and application.
Three cached Simpler mappings were reused with zero network/provider requests
in that regression. Raw source pages and private cache files remain uncommitted.
Other generic NSF/program links are not promoted to identities without evidence.

The daily failure in runs 35112161731 and 35237280995 occurs after successful
source generation and validation: the Actions account requests a Codex review
but has no working connector, then a thirty-minute wait throws an error. The
workflow now retains an explicit `awaiting_review` publication artifact after
a bounded 90-second initial wait. No serving mutation, provider smoke, merge or
Pages deployment follows that state. Actual findings, integrity failures and
review-service outages still fail. It is not a successful publication.

On an ordinary later run, the planner selects that exact open bot-owned PR and
artifact only if its head, candidate, protected generation ancestry and current
dependencies still match. It resumes `publish`, reusing exact validation where
valid, rather than paying to regenerate while review is pending. Changed source
inputs still use the ordinary dependency planner. An explicit named resume never
substitutes a different candidate.

A connected maintainer still must initiate one actual review if the Actions
request is not acknowledged. This repair does not introduce credentials or
repurpose researcher-specific publication tokens. After a clean exact-head
review, use the existing manual release workflow with stage=`publish`, the
retained artifact run and complete candidate ID. The existing protected merge,
Worker compatibility/smoke, Pages and live verification gates remain required.
No schedule, permission, provider allowance or experimental team activation changes.

Local checks: 76 focused Python tests and 10 Node/browser lifecycle contracts
passed. No E2E/Playwright or scientific provider requests were run. One local
Windows line-ending fixture failure was corrected by restoring the repository
LF checkout convention; required Linux CI and exact-head review follow.


PR #260 review5240948885 on `077ff33959f9df73ab2dbea508b7429380a2ae1c`
identified a supported-path conflict: an existing number/stable-ID winner could
bypass an official link naming another record. The reproduction attached B's
link to A. The consolidated repair reconciles all preselected identities and
all official links before moving any evidence, including a linked record absent
from the current feed. Conflicts fail closed. Consistent identity remains
idempotent. Twenty-four focused checks (including 18 conflict combinations)
and the unchanged real 1,395-to-1,391 replay pass. The first new fixture incorrectly
requested VPR resolution after replacing its ID with a native ID; correcting
fixture order exercised the actual cached-receipt path. Exact-head re-review
and required CI are required before merge; earlier CI is historical evidence.
