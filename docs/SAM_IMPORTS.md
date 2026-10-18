# SAM.gov research-call imports

The reviewed inventory in `config/sam_gov.json` uses schema version 2. It expands
the original one-notice BARDA pilot using a documented review of the retained
65-notice discovery result and current official agency research inventories.
See `SAM_CATALOG_REVIEW_20261013.md` for coverage, dispositions, and evidence.
Inclusion means an academically eligible, actionable research-call entry route
was verified; it does not claim the opportunity exists exclusively on SAM.

## Collection and admission

Every enabled refresh checks each approved exact notice ID using SAM's anonymous
public notice and attachment-manifest routes, the same public information served
by the SAM website. It reads two endpoints per notice, at most four notices
concurrently. Each endpoint allows at most two 15-second attempts and one second
of retry delay for temporary HTTP 403/429/5xx or network failures. Successful
endpoints are not fetched again. A longer server-requested wait ends this bounded
attempt instead of retrying early. Responses have an 8 MiB cap; redirects,
malformed responses, and other HTTP errors are not retried. Every attempt is
counted, and terminal errors retain a sanitized failure classification. The
collector may follow one exact public latest-version pointer per approval,
reading the same two endpoints for that successor. It never discovers candidates
by title or follows another pointer. The 100-notice limit therefore has a nominal
transport bound of 51 minutes 40 seconds; the manual preview allows 60 minutes. No API
key, cookie, attachment body, contact information, or raw notice description is
included in the resulting snapshot.
The current manifest is checked; attachment bodies are downloaded during source
review, not every refresh. A response fingerprint is not a claim to have read a
document again.

The exact notice ID, complete solicitation number, numeric SAM organization ID,
current publication state, description hash, and attachment-manifest hash bind
the reviewed approval. An optional complete `reviewed_snapshot` must authenticate
that approval's exact existing fingerprint and contain only the bounded safe
snapshot fields. If all material snapshot fields still match, the collector may
relink the current exact notice ID across an administrative version change.
Only notice IDs, latest-version pointers and posting/modification timestamps may
change under that proof. Description and attachment-manifest digests, sponsor
organization, full solicitation number, title, dates, restrictions and all other
material fields remain exact. Repackaged attachment IDs still require review
because the retained manifest cannot establish their body equivalence.
Changed active evidence or an unresolved successor requires review and stops
generation before paid work or candidate persistence.
Restrictive set-asides, cancellation, archiving, expired entry stages, approval
expiry, and identity changes cannot be admitted by a matching title alone.
Source-reviewed Special Notices and Presolicitations can represent actual open
research calls; a generic notice-type or title keyword cannot decide eligibility.

Configuration supports at most 100 approvals and requires explicit official
academic-eligibility evidence, a scientific summary, material scope conditions,
and source-cited submission cycles. Original scientific approvals have a review
window of at most 30 days. A complete exact-material proof may establish fresh
currentness after that window without changing `verified_on`, `review_after` or
the original approval digest. The record and diagnostics retain those original
dates plus the current verification date, seven-day currentness limit and both
exact notice fingerprints. Actual entry dates, archive dates and cycles are
never extended. Without that full proof, approval expiry still withholds the
record. A successful HTTP response alone cannot renew it. Removed approvals revoke
retained records. Transport/schema failures are reported as source degradation,
without publishing unverified SAM fallback records. The generation workflow
requires a complete, healthy reviewed SAM scan in a separate preflight before
the generation job, allowance reservation, or other source collection starts.
The preflight retains safe normalized snapshots and diagnostics, including a
failed review disposition. Generation replays those exact public inputs without
another SAM request. The receipt binds the exact configuration bytes, protected
checkout SHA, event SHA and GitHub run/attempt, retaining its original UTC source
date and check timestamp. Replay accepts at most two hours of source age and
reevaluates admission at the merge's current UTC date, including newly closed
entry stages. Crossing midnight does not relabel the original source proof; missing,
mismatched or malformed receipts fail closed. This artifact is only a same-run
source-read optimization, never candidate identity or publication evidence.
If a request remains unavailable after bounded retries,
or current evidence cannot be parsed, that generation stops and the previously
published catalog remains in service. It preserves source diagnostics and the
existing spend checkpoint and emits a failure alert. A successful scan that
proves closures, restrictive eligibility, or expired/revoked approvals may remove those calls;
an unavailable scan cannot publish an apparent withdrawal of the SAM inventory.
The guard is included in generation dependencies, so a candidate created before
this protection cannot be silently reused under the new contract.

All 42 October 13 retained snapshots exactly authenticate their original
approval fingerprints and provide the safe baseline for this continuity check.
IMR's October 16 Amendment 01 changed material evidence and was reviewed
separately on October 18; see `SAM_IMR_REVIEW_20261018.md`.

Legacy schema version 1 remains supported for existing contracts and offline
regressions. Its credentialed one-page search for the literal title phrase
"Broad Agency Announcement" in the previous 364 days was bounded discovery, not
a comprehensive inventory. Production version 2 no longer depends on that phrase
or posting window. The stored SAM key is retained for the legacy API/access
checks and is never placed in configuration, shell arguments, or reports.

## Submission stages and duplicate handling

An entry can be a full application, white paper, concept paper, preproposal,
preapplication, or letter of intent. A later full proposal may require invitation
and may have no publicly specified date. The adapter preserves those facts,
including the source's time zone and individual annual cycles. Once a mandatory
entry closes, its later invited deadline does not keep that cycle open to a new
applicant. Optional preliminary discussions do not become mandatory gates.
Umbrella end dates are not invented full-proposal deadlines.

Scientific scope restrictions and conditions appear in the record description.
Classified branches, closed topic calls, and restricted-only routes do not become
open academic opportunities merely because the parent BAA remains active.
The catalog's existing sponsor/full-solicitation identity rules still apply.
Grants.gov remains authoritative when the verified sponsor and full solicitation
number identify the same opportunity; different display titles or SAM amendments
do not justify duplicate records.

When a reviewed SAM notice replaces another public notice ID, a SAM-owned
record keeps the current ID and retains the former ID as a source alias. Native
SAM continuity requires a unique matching sponsor, full solicitation number and
exact SAM organization. If Grants.gov or another existing source owns the
canonical record, its proven SAM aliases retain continuity under the existing
sponsor/solicitation identity rules.
The previous published catalog supplies identity evidence only. Old
science, dates and currentness are never copied. Later refreshes retain these
aliases so saved calls, opportunity watches and change-feed continuity survive
administrative notice replacement. Ambiguous ownership or conflicting aliases
stop publication rather than attach a watch to another call.

## Preview and release

Run **Preview SAM.gov catalog imports** on `main`, leaving the optional legacy
description IDs empty. Version 2 checks the approved exact notices once, then
reuses those observations in the actual canonical merge with writes and unrelated
network enrichment disabled. Its sanitized report records request counts,
fingerprints, admission failures, catalog identity comparisons, and validation.
It does not modify the catalog, source cache, teams, or provider state.

The same preview can run locally:

```text
python -m tools.sam_import_preview --report /temporary/path/sam-preview.json
```

Admission/configuration changes require the normal exact-head PR review and
Python/browser contracts. Source code and configuration participate in the
generation fingerprint. After merge, the immutable catalog release must generate,
validate, publish, and verify the expanded candidate. Generated assets are not
manually edited. Team generation, document-AI limits, search-vector limits, and
the deleted 15-minute chat automation are unchanged.

## BARDA continuity

BARDA `BAA-23-100-SOL-00004` retains the same canonical SAM identity. Its current
Amendment 7 was downloaded again on October 13 and matched the previously reviewed
SHA-256 `72aeb8532f7c48e8e4c17c8f50e17f4a9f125cf52a33b4551c0c7e31dcf002d6`.
Page 6 admits academic institutions; pages 9 and 26 allow direct proposals through
September 25, 2028 at 16:30 Eastern, subject to AOI-specific terms. Recommended
preliminary assessment remains optional.
