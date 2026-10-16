Official source excerpts retrieved September 5, 2026:

- `darpa.json`: https://www.darpa.mil/json/opportunity.json (selected research and excluded-notice rows; empty/populated join duplicates retained).
- `shine.html`: https://www.darpa.mil/research/programs/shine
- `resilient.html`: https://www.darpa.mil/research/programs/resilient
- `qbi.html`: https://www.darpa.mil/research/programs/quantum-benchmarking-initiative
- `iarpa_empty.html`: https://www.iarpa.gov/engage-with-us/open-r-d-opportunities

The program fixtures retain the body and solicitation blocks used by the adapter.
IARPA had no open R&D opportunities at retrieval. The synthetic open IARPA
case in the test module uses the status/date structure inspected on the closed
https://www.iarpa.gov/research-programs/video-lincs page; it is not live funding.

`catalog.json` is the canonical output for these four DARPA calls and the
synthetic IARPA case. Python verifies its records, index and facets against the
adapter; browser contracts use it without requiring Python dependencies.

Liquid Surge excerpts retrieved October 16, 2026:

- `liquid_surge.json`: the exact selected rows from the official DARPA discovery
  inventory at https://www.darpa.mil/json/opportunity.json, retaining its three
  empty-summary duplicates and one populated-summary row.
- `liquid_surge.html`: the body and exact DARPA-PA-25-07-05 solicitation block
  from https://www.darpa.mil/research/programs/liquid-surge. The original full
  page SHA-256 was `3cc39805fca75f018cf9257f2bee947704032669ceabeed9b3cda5d525b08e01`.
- `liquid_surge_record.json`: the adapter's October 16 output from these
  excerpts, checked by Python and shared with focused browser contracts.

The source lists an Abstract deadline of November 3 and a Proposal deadline of
December 14. It does not state whether the abstract is required; that remains
unknown. The bounded excerpts are test evidence, not production refresh inputs.
