# SAM.gov catalog import preparation

`config/sam_gov.json` enables one reviewed BARDA notice, verified on 2026-10-12
with approval through 2026-11-11. Every other SAM notice remains outside the
allowlist. Configuration admission is separate from catalog publication: the
normal protected refresh must still collect, validate, and publish the record.
Saving `SAM_API_KEY` alone does not approve any notice.

## What is connected

The `sam-gov` adapter produces normal canonical Federal records and enters the
existing source lifecycle, sponsor/solicitation deduplication, catalog validation,
indexing, and source-health reporting. Grants.gov remains authoritative when a
verified sponsor and complete solicitation number identify the same opportunity.
The SAM secret is available only to source collection and the manual preview
step. No generated catalog assets are edited by the setup or preview.

The pilot queries titles containing **Broad Agency Announcement** over the last
364 days. This is a bounded discovery scope, not complete SAM coverage and not an
academic-eligibility test. It reads all returned notice types so an observed
archive or award can retire an approved open notice. It makes one request with
`limit=500`, `offset=0`, no redirects/retries, a 30-second timeout, and an 8 MiB
response cap. An incomplete page fails; it never becomes a successful inventory.
A valid empty response is distinct from an API/authentication failure.

Only explicitly reviewed entries in `approved_notices` can enter the catalog.
The live response must still match the reviewed notice ID, full solicitation
number, and organization hierarchy. A record also needs an active solicitation,
a current response deadline, an R&D classification, and no restrictive set-aside.
A BAA title or classification alone cannot admit a record. Unreviewed discoveries
remain in the preview, outside publication.

## Current reviewed pilot

The approved identity is **BARDA BAA-23-100-SOL-00004**, SAM notice
[`8170c4735df64714adb2d1f8ce8671b1`](https://sam.gov/workspace/contract/opp/8170c4735df64714adb2d1f8ce8671b1/view),
under the API organization hierarchy stored verbatim in the admission config.

The [2026-10-12 live preview](https://github.com/mporosoff/grants-scraper/actions/runs/38273049220)
returned one complete 65-row listing and made one selected BARDA description
request: **two SAM requests total**. BARDA was an active Solicitation, with
classification AN13, NAICS 541714, no listed set-aside, and response deadline
**2028-09-25 at 16:30, UTC-04:00 (Eastern)**. Its API posting date remained
2026-03-20, matching the previously observed Amendment 7 attachment date. This
agreement does not establish that attachments were downloaded or reverified on
October 12. The sanitized API description produced no excerpts and explicitly
left eligibility unverified.

Academic eligibility instead comes from **BARDA FY23 Modernized BAA Solicitation,
Amendment 7, page 6**, retrieved on 2026-10-01 and reviewed again on 2026-10-12.
Its exact passage admitting academic institutions is retained in the config.
The reviewed PDF SHA-256 is
`72aeb8532f7c48e8e4c17c8f50e17f4a9f125cf52a33b4551c0c7e31dcf002d6`.
The [official BARDA page](https://www.medicalcountermeasures.gov/barda/barda-baa)
links this SAM notice. API metadata confirmation and review of this saved PDF are
the evidence basis; a new attachment download is not claimed.

Stage 2 assessment using a Quad Chart, Market Research Abstract and Rough Order
of Magnitude is recommended. It is **not a mandatory prerequisite**: page 24
states that an unfavorable assessment does not preclude a proposal, and page 26
expressly permits proposals without a Stage 1 call or Stage 2 submission.
Page 9 gives both Stage 2 and Stage 3 the September 25, 2028, 16:30 Eastern umbrella
deadline unless an Area of Interest (AOI) says otherwise; invitation letters may
specify additional dates. The existing open application event is therefore
appropriate, with no universal invitation flag. Applicants must follow the
current AOI, readiness, BDR Portal, SAM registration, unclassified-submission and
proposal-validity requirements.

**MEAS-6 rationale revised for this pilot:** the measured benefit is filling a
current catalog gap with authoritative contract-notice information, not proving
SAM-exclusive publication. The 1,261-record catalog had no exact solicitation or
BARDA title match. Two current Grants.gov keyword comparisons on 2026-10-12
returned 45 results for the full number and one for BARDA, with no exact-number
match. Keyword-index absence is not proof of absence from Grants.gov; the BAA
itself describes availability there. This explicit catalog-coverage rationale
supersedes the historical SAM-only prerequisite for this one-notice pilot.

## Run the bounded preview

In GitHub Actions, run **Preview SAM.gov catalog imports** on `main`. Leave
`description_notice_ids` empty for one listing request, or select at most two
comma-separated IDs returned by discovery for at most three requests total.
The optional description requests use only validated SAM API routes for those
exact listed notices. They do not follow links, download attachments, or retry.

The artifact contains safe listing metadata, possible catalog identity matches,
the real canonical merge preview, and short description excerpts for review.
Full descriptions, raw responses, credential-bearing URLs, and secrets are not
retained. Detected contact email addresses, telephone numbers, and contact links
are removed before excerpt selection; this does not attempt to identify people's
names. Short descriptions produce no excerpts. Longer descriptions produce at most
five separate excerpts of 400 characters each, totaling no more than half the
sanitized description and never more than 2,000 characters. An empty excerpt list
is an evidence gap, not an eligibility decision. The description hash can identify
the response for review without retaining its full text.
The preview uses the fetched listing once and never writes the catalog/cache.

Local development with an already configured private `SAM_API_KEY` uses:

```text
python -m tools.sam_import_preview --report /temporary/path/sam-preview.json
```

Do not paste a key into shell arguments, configuration, artifacts, or chat.
The dedicated personal SAM key's quota is unknown: the access test returned no
rate headers. Do not assume the old planning estimate of 1,000 requests/day.
Keep the initial preview to one run and inspect its outcome before further calls.

## Activation evidence

Before setting `enabled` to `true`, populate reviewed pilot entries with:

- `notice_id`: the exact SAM notice ID.
- `solicitation_number`: the complete official number, including any call suffix.
- `organization_path`: the exact SAM organization hierarchy.
- `sponsor`: the verified canonical sponsor name used for cross-source identity.
- `evidence_url`: the official public source supporting the review.
- `academic_eligibility_quote`: a short exact passage supporting academic eligibility.
- `verified_on` and `review_after`: ISO dates, no more than 30 days apart.

Verify an actual proposal/submission route and the current call's terms; a parent
BAA can be open for years while accepting proposals only under individual calls.
Check exact SAM notice links and full sponsor/solicitation identities against the
catalog, other adapters, and Grants.gov. Absence from our catalog does not prove
SAM-only availability. The earlier MEAS-6 requirement to name a relevant SAM-only
notice, or explicitly revise that rationale, is addressed for the current
BARDA pilot above; later scope expansions need their own evidence.

Review the config change through the normal protected PR process, run a preview
with approved entries, and verify the resulting canonical IDs, deadlines,
eligibility, duplicate decisions, and catalog validation. Both SAM code and config
are included in source-generation fingerprints, so changed admission rules cannot
reuse a candidate generated under old rules. Then enable the reviewed pilot through
that same configuration. The normal refresh uses the stored secret automatically.
Wider query coverage, historical backfill, and general description/attachment
harvesting require a separately bounded expansion of this pilot.

## Currentness and failure behavior

Posting windows are incremental observations, not modification watermarks.
The adapter preserves still-current unobserved records only through their existing
review bound, at most seven days and never beyond the approval's review date.
Explicit archived/expired/closed observations retire earlier open records.
Removed, expired, or changed approvals invalidate retained records immediately.
Uncertain or changed source identity is withheld without claiming an official
withdrawal. API/schema/quota failures produce sanitized source degradation and
publish no unverified SAM fallback. Other sources continue through their existing
lifecycle. The source-health issue provides the operational failure signal.

## Primary references

- [SAM opportunities API](https://open.gsa.gov/api/get-opportunities-public-api/)
- [API gateway errors and quota headers](https://api.data.gov/docs/developer-manual/)
- [SAM account guide, quota tiers on page 6](https://dodprocurementtoolbox.com/uploads/System_Account_User_Guide_v3_01_5f66649acf.pdf)

These operational limits supersede the historical quota/cache assumptions in
`docs/TOPIC_LAYER_PLAN.md` section 7.5. No SAM-only benefit or academic eligibility
is claimed solely from the successful credential test.
