# Completion checker baseline evidence

These bounded operational fixtures come from the retained authoritative state of
workflow run `35616677156`, attempt 1, at
`f70f000f5977b923cc7e495e0a80be1a3ce84090`.

- `request.json` is the exact final ledger row, canonically serialized.
- `receipts.json` and `diagnostics.json` preserve the original file bytes for
  request `c1d338226c57473ea464d002121b0167`; their file hashes and canonical
  diagnostic identity are recorded in `baseline.json`.
- `native-counts.json` preserves all 188 existing native token-count rows and
  their checkpoint version/source identity. These rows contain bounded request
  identities and counts, without prompts or scientific response text.
- `baseline.json` records verified accounting and historical identities. All
  1,363 files named by the retained checkpoint were verified against their byte
  hashes. The actual saved Luna assessment and frozen scientific inputs passed
  `contextual_team_compact_check.packet` validation before this fixture was made.

The failed checker returned HTTP 400 because the compiled strict grammar was too
large. Its full $0.20 unknown hold is retained. The fixture contains no successful
independent verdicts and does not represent checker completion. It does not
contain raw provider caches, prompts, scientific evidence, or Luna rationales.

The full ledger and checkpoint remain private retained evidence; these fixtures
are not a second ledger or a replacement for authenticating the terminal run.
