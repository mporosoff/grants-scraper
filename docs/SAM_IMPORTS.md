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
by the SAM website. It makes two bounded GET requests per notice, at most four
notices concurrently. Each request has a 30-second timeout and an 8 MiB response
cap, without redirects or retries. No API key, cookie, attachment body, contact
information, or raw notice description is included in the resulting snapshot.
The current manifest is checked; attachment bodies are downloaded during source
review, not every refresh. A response fingerprint is not a claim to have read a
document again.

The exact notice ID, complete solicitation number, numeric SAM organization ID,
current publication state, description hash, and attachment-manifest hash bind
the reviewed approval. A changed or superseded notice is withheld for review.
Restrictive set-asides, cancellation, archiving, expired entry stages, approval
expiry, and identity changes cannot be admitted by a matching title alone.
Source-reviewed Special Notices and Presolicitations can represent actual open
research calls; a generic notice-type or title keyword cannot decide eligibility.

Configuration supports at most 100 approvals and requires explicit official
academic-eligibility evidence, a scientific summary, material scope conditions,
and source-cited submission cycles. The reviewed approval remains valid for at
most 30 days. The source lifecycle also caps retained freshness at seven days and
never beyond that approval. Expiry requires another evidence review; it is not
automatically extended by a successful HTTP response. Removed approvals revoke
retained records. Transport/schema failures are reported as source degradation,
without publishing unverified SAM fallback records.

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
