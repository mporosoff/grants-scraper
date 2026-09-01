# Opportunity-to-Team Rollout

## Decision

Funding Finder may propose a three- or four-person research team only for a
specific opportunity, a publication-eligible child topic, or a source-declared
branch. Broad parent programs are never automatic team units.

The first calibrated release contains ten opportunity scopes spanning eight
collaboration archetypes. It is deliberately a staged evidence model: two
teams pass the complete-internal-team gate, seven are credible internal cores
with explicit missing skills, and one demonstrates insufficient internal role
coverage. An incomplete proposal must remain visibly incomplete.

## Data boundary

`config/opportunity_team_model.json` is the canonical repository model. It was
deterministically reduced from the offline faculty-evidence expansion and the
ten-opportunity explanation gate. Those workbooks and larger calibration JSON
files are import artifacts and are not browser assets.

The source contract is:

- 156 faculty directory records;
- 145 source-rankable and 11 source-unrankable records;
- 118 main-pool candidates with at least two retained capabilities;
- 35 standby records with exactly one retained capability; and
- 3 directory-only records with no retained matching capability.

Source rankability describes what the controlled workbook supported before the
later source-evidence audit. Pool assignment describes the retained,
source-traceable capability model after that audit, so the two classifications
are intentionally reported separately rather than treated as the same partition.

The compact browser projection is `data/opportunity_teams.js` and remains lazy.
The eager `data/opportunity_team_index.js` contains only the ten reviewed scope
identifiers, their parent identifiers, and record types; it contains no faculty,
role, or explanation graph. Both assets share an immutable generation identifier:
the SHA-256 of the canonical model payload before the identifier is added.
Funding Finder and Team Match declare that identity in their HTML markers and
all changed runtime/cache references. Runtime validation rejects a mismatched
index or projection. The search release manifest hashes both generated assets,
both pages, and every changed runtime file, and Pages verification checks the
published bytes against those hashes.

The controlled workbook source hash is
`4cc24fad355c5716a462b93e1f60d0c7d55d9368d7cfede330ff41daa36af130`.

## Evidence and team contract

Every supported opportunity has four required roles. A role records:

- the role label derived from an authoritative opportunity source;
- a bounded set of accepted controlled capabilities;
- direct, method-transfer, adjacent, or gap status;
- the person or people individually audited for that role;
- evidence-backed alternatives that still require role-transfer review; and
- the role rationale and source URL.

Direct and method-transfer evidence may fill a required role. Adjacent evidence
is displayed as support but does not silently make an incomplete team complete.
An evidence-backed alternative also remains review-required until its role
transfer is audited. Every selected initial member retains a contribution,
source-backed capability phrase, person-level explanation, faculty source, and
source-check date.

Team assembly optimizes complementary role coverage, not pairwise similarity.
The interface explains why the people work together and why each person was
selected. Removing a person recomputes role coverage. Replacement options are
limited to source-backed candidates for the newly missing roles, and an
unreviewed transfer cannot claim completed coverage. When no defensible
internal replacement exists, the interface says so and provides a prominent
manual-collaborator route.

## Runtime eligibility

Generated membership never overrides the live catalog. The reverse-team panel
uses the same browser currentness predicate as ordinary retrieval and Team
Match, evaluated against one clock captured when the panel opens. A record that
has expired, been archived, become stale-undated, or moved to an ineligible
status is rejected even if the generated model still contains it. An explicit
past close date is authoritative even when a record is also labeled rolling;
rolling applies only when no explicit deadline exists. Forecasted records keep
the existing product treatment.

Publication-eligible child topics are rechecked against the current lazy child
catalog. A generated child that is not in that eligible projection is rejected.
Declared branches retain their official branch source. A broad parent with one
or more calibrated branches presents a scope chooser instead of a team.

## User experience

Funding Finder shows the lazy “Build a team” action only on cards whose exact
scope, reviewed child/branch, or parent scope chooser exists in the generated
availability index. The toolbar's separate “Build a team” toggle filters the
current result set, exports, pagination, and chat context to those supported
opportunities without loading the full graph. Only one team panel may be open.
A result rerender closes the owned panel and clears its trigger state, so
detached nodes cannot block a later activation. Close and Escape restore focus
when the trigger remains connected. A team-data failure is isolated from search
and other card actions.

Team Match adds an accessible local combobox labeled “Search Hajim faculty at
the University of Rochester.” Results show main, standby, or directory-only
status. Directory-only records cannot be admitted without better evidence.
The separate “Add a researcher manually” path preserves saved researchers,
ORCID import, the four-person limit, and device-local storage. A Funding Finder
proposal can be carried into Team Match through public faculty identifiers; no
private research text is put in the URL. Directory selections paint a visible
highlight, move focus to the selected team chip, and announce the matching
refresh before the heavier local matching pass. Saved directory members use
stable public identifiers and load directory identities before restoration.

## AI boundary

No AI call is required for the first-stage team proposal. Deterministic catalog
membership, role evidence, currentness, child publication eligibility, and
completion status remain authoritative.

A later provider-connected refinement may interpret a specific notice into a
bounded role plan or synthesize the displayed rationale, but it may not invent
faculty evidence, opportunity identifiers, team membership, or completed role
coverage. That extension requires a separate calibrated test frame and is not
part of this release.

## Expansion workflow

Each subsequent calibration batch should:

1. select only current, specific parents or eligible/declarative child scopes;
2. draft four bounded required roles from authoritative source text;
3. audit every proposed person and every role edge against faculty sources;
4. preserve unsupported roles as gaps instead of force-fitting a profile;
5. run holdout removal/replacement checks and unrelated-child controls;
6. add the accepted batch to the canonical model;
7. regenerate the browser projection and HTML identity references together;
8. rebuild the search release manifest; and
9. run focused model/runtime/accessibility contracts before protected checks.

Coverage breadth, faculty-faculty similarity, and counts of possible three- or
four-person permutations are diagnostics only. They do not establish team
quality.

## Known limitations

- The directory may still omit relevant faculty, including secondary or
  cross-school collaborators.
- Fifty faculty claims remain marked for lexical review and 54 expanded claims
  still require specific verification if challenged.
- Seven of ten initial proposals remain conditional and one remains a failed
  internal-coverage example.
- Replacement alternatives with source-backed vocabulary remain visibly
  review-required unless individually audited for the opportunity role.
- Availability, willingness, sponsor eligibility, budget, and institutional
  approvals must be verified outside the tool.
