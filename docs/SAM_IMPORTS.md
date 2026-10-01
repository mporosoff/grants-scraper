# SAM.gov catalog import preparation

SAM access was verified on 2026-10-01 with one successful public opportunities
request. The adapter is staged in the normal source registry, but production
imports remain disabled in `config/sam_gov.json` until the pilot evidence below
is reviewed. Saving `SAM_API_KEY` alone does not activate imports.

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

## Run the bounded preview

In GitHub Actions, run **Preview SAM.gov catalog imports** on `main`. Leave
`description_notice_ids` empty for one listing request, or select at most two
comma-separated IDs returned by discovery for at most three requests total.
The optional description requests use only validated SAM API routes for those
exact listed notices. They do not follow links, download attachments, or retry.

The artifact contains safe listing metadata, possible catalog identity matches,
the real canonical merge preview, and short description excerpts for review.
Full descriptions, raw responses, contacts, credential-bearing URLs, and secrets
are not retained. Description excerpts are evidence to inspect, not automatic
eligibility decisions. Missing text is reported as a gap, not inferred eligibility.
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
notice, or explicitly revise that rationale, remains an activation gate.

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
