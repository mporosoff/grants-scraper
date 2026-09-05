# Public polish and institution selection

The September 5 request explicitly authorizes continuous convergence through
merge, plus complete E2E/Playwright validation. It resumes PR #140 at
`d6caced49ab604ee4048ab10f74bbfb54e91de80`, based on protected main
`b9cb5b714b1ee9d5fccd83368dc8ecb8e4951177`. Main and the complete open-PR inventory
were checked again; PR #140 is the only open PR. Earlier convergence checkpoints
remain preserved in `outputs/stage5`.

## Requested behavior

- Funding Finder keeps its original hero, heading, introduction, background and
  search surface after a search. Its existing results/refine controls still reflect
  search state; search membership, ranking, history and scroll owners are unchanged.
- Funded Awards receives the same blue hero palette and heading hierarchy while
  retaining source-native criteria, result views, its four-source badge, and Ask AI.
  Team Match retains the desktop sidebar and single mobile editor implemented by
  Stage 4. These changes were previously pending in this PR, not live on main.
- Team Builder permits headings, status badges, member rows and role labels to
  shrink and wrap within the drawer. The visible focus indicator remains enabled.
  Browser checks cover 320/390 px with normal and enlarged root text.
- Add/correct researcher has an optional Institution combobox using the existing
  Funded Awards ROR endpoint and configuration. Only the typed institution query is
  sent to that public lookup; no researcher information accompanies it. Selection
  retains the canonical name and ROR URL. Editing clears the selected URL. Debounce,
  cancellation, request sequencing and timeout prevent late responses from changing
  a different draft. A complete typed name remains usable during lookup failure.

ROR choices display the city and country from the award API's normalized location
fields, matching Funded Awards. A duplicate-name regression uses the real Worker
normalizer to ensure different institutions remain distinguishable and keyboard
selection retains the intended canonical ROR identity.

## Institution data and governance

The additive optional field is `institution: { name, ror_id }`, bounded to 300
characters for the name and a canonical `https://ror.org/0…` identifier (or empty
identifier for a typed name). Client and server enforce its allowlist and bounds.
Old submissions retain their exact shape. Omitted fields in older corrections
preserve existing metadata; explicit empty values permit a reviewed removal.

Institution changes are administrative metadata. They do not assign a researcher
identity, establish a verified affiliation, change a relationship/visibility policy,
grant team eligibility, or change claim IDs/revisions. The private review comparison
shows institution name and ROR identity, and the ordinary administrator approval
and registry publication path persists the approved values. Registry validation
enforces the same bounds; existing generated outputs remain byte-identical when
the new field is absent. No existing researcher is assigned an inferred institution.
Browser-only profiles retain optional institution metadata without changing their
IDs, handoff tokens, selected identities, matching terms or AI payloads.

No database migration is required: proposals are already stored as bounded JSON.
The existing researcher-intake deployment workflow publishes the additive server
contract. Public receipt and consent behavior, access controls, private contact
handling, review revisions and publication recovery remain unchanged.

## Update and regression safeguards

The shared asset checker now requires exactly one real script/stylesheet reference
for every required integration on each public page. Commented-out and duplicate
tags cannot satisfy it. The complete family is validated before any write, with
deletion/duplication/comment fixtures for every required reference. New ROR helpers
have separate presence and exact-content-version contracts.

Existing source/function baselines remain in place. The four files necessarily
changed for the hero or optional institution metadata additionally preserve every
pre-existing function outside the specifically authorized functions in
`user-fixes-preserved-functions.json`. Governed form controls retain their individual
attributes and rules; the entire form is no longer frozen as one markup hash, since
the user explicitly requested a new field.

The dedicated Playwright cleanup updates assertions for renamed copy and requires
opening the mobile team editor before interacting with its controls. Complete
protected CI, exact-head review, manual E2E results and post-merge deployment
evidence are recorded in PR #140 and `outputs/stage5` once completed.

The broader E2E audit also routes profile, filter and provider interactions through
the visible Refine Search drawer, closes it before returning to the page, and waits
for ordinary search settlement before opening a transient card menu. Existing
ranking, CSV, identity, stale-response, consent, provider and history assertions are
retained. Geometry checks measure containment and non-overlap without assuming
the retired vertical action stack or an absolutely centered navigation cluster.
The earlier Stage 2 whole-file freeze for `team-researchers.js` is superseded only
for optional institution normalization; the function-level baseline freezes its
remaining pre-existing functions and the additive metadata tests cover the change.

The first complete manual E2E attempt on `77ce7a7` was interrupted after the
systematic stale-control failures were audited. It is diagnostic evidence, not
passing validation. The corrected candidate receives a fresh complete manual E2E
run and protected CI; automatic refresh continues to exclude E2E.
