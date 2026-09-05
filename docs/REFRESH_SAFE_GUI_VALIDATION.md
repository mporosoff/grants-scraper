# Refresh-safe GUI validation follow-up

The protected GUI/polish merge `824f79f05599686185714b9057d40d3cd256fc94`
passed 824 Python tests, 655 browser contracts and 110 manual E2E scenarios.
Live desktop, 390 px and 320 px checks confirmed the deployed page bytes, ROR
selection, persistent hero, saved feedback and fully loaded Team Builder layout.

Its automatically triggered catalog refresh then correctly stopped before
publication because the Stage 4 redesign contract compared the newly generated
release hashes and timestamp to the historical audit generation. This was an
incorrect permanent constraint: a valid refresh necessarily changes those values.
The same snapshot family also froze six mutable researcher/team projection or
registry inputs, which would block a later legitimate reviewed publication.

The follow-up keeps byte-level algorithm and request-owner baselines, release
field structure, model, dimension and atomic-publication rules. Dynamic release
values instead remain bound to the current manifest, vector bytes, canaries and
Worker allowlist. Existing exact registry generation, faculty-match content cache,
opportunity-team identity and publication contracts remain enabled. Additional
checks bind generation time, model, dimension and passage count to the current
manifest. Historical data hashes remain recorded as audit evidence, not as a ban
on future refreshes or reviewed registry changes.

An immutable baseline from protected main records all 158 existing researcher IDs,
their legacy mappings, and 432 claim IDs with legacy mappings, revisions and material
hashes. Current registry publication must retain these addressable identities;
revisions cannot regress, and unchanged revisions cannot silently change claim
material. Reviewed content changes, additional identities and retired claims remain
possible. Fault-injection tests reject removed, renumbered or reassigned identities
independently of whether someone also rebuilds every generated projection.

The mobile clipping regression now waits for an actual team member before testing
headings, badges and rows at normal and enlarged text sizes; the loading placeholder
cannot satisfy the test. This follow-up changes only validation and documentation.
Automatic refresh still excludes Playwright/E2E; a dedicated complete manual E2E
run and exact-head review validate the follow-up before merge.
