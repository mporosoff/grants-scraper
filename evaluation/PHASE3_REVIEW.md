# Phase 3 deployment review

**Scope update — October 16, 2026:** The owner retired the standalone human pilot/review and recruitment/handoff project. This file remains an optional tooling/privacy reference, not a pending project or release gate. Current development follows [the Team Match objective](../docs/TEAM_MATCH_OBJECTIVE.md); missing historical review evidence is not relabeled as completed.

This historical workflow was designed to check official FOA evidence and return a private review before a researcher pilot. The owner retired that standalone review/pilot project on October 16, 2026. Existing privacy-safe review tooling remains optional; no new return or participant exercise is required by this document.

## What the site records

Nothing is submitted automatically.

One device-local record, `funding-finder.deployment-review.v1`, autosaves:

- an optional reviewer code;
- explicit source verdicts (`accurate`, `incorrect`, or `couldn’t verify`);
- the public opportunity, document hash/version, cited evidence identifiers,
  checked field, and optional reviewer note;
- five deployment checklist answers;
- coarse viewport, locale, timezone, and file-share capability fields; and
- aggregate counts of searches, profile searches, AI matches, chats, official
  source opens, citation opens, and exports.

The record does not contain API keys, CV/profile text, search text, Funding
Finder search URL/parameters, or chat. An optional note is user-authored, so reviewers must not
enter confidential or unpublished research.

Match-quality labels from Phase 2 may be included in the Phase 3 handoff, but
their query text, notes, and profile fingerprint are removed.

## Reviewer workflow

1. Search for one or more realistic opportunities.
2. Confirm that the primary FOA or agency notice opens in one click.
3. For a record with Phase 3 evidence, expand the cited facts and open at least
   one citation.
4. Compare the extracted fact with the cited PDF page or HTML section.
5. Mark the evidence accurate, incorrect, or unverifiable. Select the field
   checked and add a brief non-confidential note when useful.
6. Complete the short deployment checklist.
7. Select **Send review**:
   - on a compatible mobile browser, choose an app from the native share sheet;
   - on desktop, attach the automatically downloaded JSON file to the addressed
     email that opens.
8. Use **Download copy** if file sharing or the email client is unavailable.
9. Keep the autosaved copy for follow-up or clear it from the page.

The project owner’s handoff address is embedded only to make the explicit
desktop return path one action. Sending still requires the reviewer to confirm
the email/share action.

## Owner intake and private storage

1. Save attached JSON files under `evaluation/inbox/`.
2. Do not commit that directory. It is gitignored.
3. Run:

```powershell
python -m scripts.summarize_phase3_reviews evaluation/inbox --output-dir evaluation/reports
```

4. Review:

   - `evaluation/reports/phase3-review-summary.md`
   - `evaluation/reports/phase3-review-summary.json`
   - `evaluation/reports/phase3-source-reviews.csv`

5. Do not commit `evaluation/reports/`; it is also gitignored.

The aggregator deduplicates repeated exports by review ID and keeps the latest
copy. Invalid files are reported rather than silently ignored.

## Historical pre-pilot gate — retired

The original checklist below described the planned pre-pilot review. It is retained as tooling history, not an active acceptance gate:

- a scheduled run publishes a nonzero real document-evidence batch;
- one PDF page citation and one HTML section/anchor citation are checked;
- a document-change fixture increments the version and opens an amendment
  review item;
- one valid AI evidence citation is rendered and one invented evidence ID is
  rejected;
- one review package reaches the owner and reproduces into all three private
  report formats; and
- mobile and desktop layouts remain usable.

These historical conditions do not start a pilot or create pending work. Missing review/handoff evidence is not claimed as completed.
