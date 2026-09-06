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
