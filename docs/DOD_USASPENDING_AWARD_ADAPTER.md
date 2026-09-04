# DoD USAspending award adapter

Checked: 2026-09-03 (America/New_York)

## Public-source boundary

The DoD adapter uses the account-free USAspending API:

- `POST https://api.usaspending.gov/api/v2/search/spending_by_award/`
- `GET https://api.usaspending.gov/api/v2/awards/{generated_unique_award_id}/`

Every search is restricted to the awarding top-tier agency `Department of
Defense`, prime awards (`subawards: false`, `spending_level: awards`), and award
type codes `04` (Project Grant) and `05` (Cooperative Agreement). Contracts,
indefinite-delivery vehicles, other assistance types, direct payments, loans,
subawards, and separate SBIR or DTIC feeds are not part of this catalog.

The search endpoint supplies the bounded result page. Detail calls are made
only for records returned to the caller or admitted to the active snapshot,
with concurrency three and successful-detail caching. A failed detail call
retains the base search record rather than converting the source to a failure;
the response marks detail health as degraded and the interface displays the
number of unavailable public detail records.
Later result pages use USAspending's stable Award ID ordering and are reached
sequentially from page one with the paired `last_record_unique_id` and
`last_record_sort_value` continuation values. The adapter never jumps directly
to a later sorted page. Public offsets are applied only after award-scope,
deduplication, year, and exact institution validation. The adapter may inspect
up to 12 upstream pages to assemble the first 25 normalized snapshot records,
but detail enrichment remains capped at those 25 admitted records.
The safety-bound flag remains true when that ceiling prevents a complete scan,
but `has_more` is true only when the adapter has already collected a normalized
lookahead record that the next client page can reach.

## Representative record

The deterministic fixtures model the public record checked on 2026-09-03:

- FAIN: `FA9550261B195`
- USAspending ID: `ASST_NON_FA9550261B195_097`
- recipient: University of Maryland, College Park
- awarding component: Department of the Air Force
- title: MURI: Physics and Applications of Intense, Spatiotemporally Structured Light Fields
- awarding office: `FA9550 AFRL AFOSR`
- Assistance Listing: `12.800`, Air Force Defense Research Sciences Program
- funding opportunity: `NOFOAFRLAFOSR20250002`
- signed: `2026-08-28`
- performance period: `2026-09-01` through `2031-08-31`
- total obligation: `$3,000,000`

USAspending does not provide award-level investigator names, program contacts,
or a project abstract in this record. Those fields remain empty or `null` and
the interface labels them as unavailable at the source. The description is
used as the card title, and the amount is labeled as obligated funding rather
than total anticipated funding.

## Search and link semantics

Supported DoD filters are exact award ID, description topic, recipient UEI or
canonical institution name, signed-year bounds, and an exact numeric Assistance
Listing code such as `12.800`. PI, program-officer, core-project, program-code,
program-office, and funding-opportunity filters are unavailable in the
USAspending award search contract and fail only the DoD source in a mixed
request.

After detail enrichment, each funding-opportunity number is compared with the
current Funding Finder catalog using case-insensitive exact equality. A card
links to the exact opportunity-number search in Funding Finder only when the
comparison produces one unique catalog record; the resulting opportunity card
retains its official Grants.gov source link. Zero or multiple matches fail
closed; titles and descriptions are never used for fuzzy matching.

## Validation policy

Pull-request tests use the committed search and detail fixtures and never call
USAspending live. The protected post-deployment smoke uses the exact FAIN above
and verifies a normalized DoD result with a USAspending profile and
`total_obligation` amount basis.
