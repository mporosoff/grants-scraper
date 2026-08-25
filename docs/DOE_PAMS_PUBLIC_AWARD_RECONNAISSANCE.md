# DOE Office of Science PAMS public award reconnaissance

Checked: 2026-08-25 (America/New_York)
Public system: PAMS Cloud PROD 2019 (E1), platform/build 2.0.110

## Official public entry points

- Office of Science funding page: `https://science.osti.gov/Funding-Opportunities`
- Office of Science award explanation: `https://science.osti.gov/Funding-Opportunities/Award`
- PAMS public award search: `https://pamspublic.science.energy.gov/WebPAMSExternal/Interface/Awards/AwardSearchExternal.aspx`
- Public abstract records: `https://pamspublic.science.energy.gov/WebPAMSExternal/Interface/Common/ViewPublicAbstract.aspx?rv=<public-record-guid>&rtc=24&PRoleId=10`

The Office of Science describes PAMS Award Search as the public source for award abstracts, specific funding amounts, and awards made under topical and annual Office of Science FOAs. PAMS itself labels the surface as a search for grants, cooperative agreements, and interagency awards funded by the DOE Office of Science. The search and direct public-abstract pages worked without login, registration, API key, or a personal PAMS account.

## Actual request and search flow

PAMS does not expose a documented JSON award API. The public search is an ASP.NET WebForms application:

1. `GET AwardSearchExternal.aspx` returns the anonymous search form and fresh `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, and validation fields.
2. Search submits `application/x-www-form-urlencoded` to the same stable path. Its postback target is `ctl00$MainContent$pnlSearch`, with the public search argument emitted by the page.
3. Results are rendered in `ctl00_MainContent_grdAwardsList`. Each result has stable labeled columns for award number, title, institution, lead PI, action type, and public-document options. The following detail row contains labeled values for organization code, program office, program manager, status, dates, award type, amounts, institution type, UEI, program area, register number, DUNS, and solicitation.
4. “View Abstract” uses a public record GUID to open `ViewPublicAbstract.aspx`. The direct page provides the award heading, status, institution, UEI, lead PI, program manager, current periods, and the source-authored public abstract.
5. Result-page changes are WebForms postbacks using the current response's fresh hidden fields. Page-number links emit `__doPostBack` targets. The observed default page size was 15.

A bounded form check confirmed that a fresh view-state POST returned the same exact award both with and without the anonymous cookie from the initial GET. A direct public-abstract GET also returned HTTP 200 without an incoming browser session, although PAMS set an anonymous cookie in its response. The adapter therefore obtains fresh form state for every search and does not depend on a persistent session.

## Public filters and observed behavior

The form provides source-controlled filters for:

- award number and title “like”;
- institution name “like”;
- abstract word or phrase;
- lead PI first and last name;
- program-manager first and last name;
- solicitation number and name;
- project-period and most-recent-award dates;
- award status, program area, Office of Science organization, award/institution type, amounts, geography, UEI, DUNS, and other public fields.

The site defaults to active awards and United States institutions. The adapter deliberately requests all award statuses and all countries, then applies the existing Funding Finder institution identity check to returned records.

Bounded reconnaissance cases:

| Public search | Observed source result |
|---|---:|
| Institution `University of Rochester` (site defaults) | 25 records, 2 pages |
| Exact award `DE-SC0020230`, all statuses | 1 record |
| PI `William Jones`, all statuses | 2 records, including an older `DE-FG` award |
| Program area `Catalysis`, all statuses | 326 records, 22 pages |
| Exact FOA `DE-FOA-0003612`, all statuses | 106 records |
| Abstract phrase `carbon dioxide`, all statuses | 400 displayed records, 27 pages |

The 400-record topic result may be a source display cap, so the adapter preserves it as PAMS's reported count without claiming completeness. Search order is left source-native. Program-area matching is a PAMS “like” search; exact current-opportunity links use only controlled `DE-FOA-<number>` solicitation identifiers.

A final bounded adapter smoke used the production all-status/all-country form state and requested one record per case. It reported 114 institution matches for `University of Rochester`, 2 PI matches for `William Jones`, and 326 program-area matches for `Catalysis`. Each case returned one normalized award with a direct official public-abstract URL and a successfully parsed abstract. The difference between 25 and 114 Rochester records is expected: the first reconnaissance count retained the site's active-award/United-States defaults, while the production adapter deliberately includes historical statuses and all countries.

## Identifiers, links, contacts, and abstracts

- DOE award numbers such as `DE-SC0024701` are the public award IDs.
- `DE-FOA-<number>` values are parsed only from the labeled solicitation field.
- PAMS organization codes such as `SC-32.1` are retained as program codes.
- The public abstract GUID is opaque but produced by PAMS and worked as a stable account-free official record URL during reconnaissance.
- PAMS exposes a structured lead PI and program-manager name. Co-investigators may appear in source-authored abstract prose, but not in a consistent structured field; the adapter does not infer structured co-PI records from that prose.
- The inspected public pages did not expose PI or program-manager email fields. Emails remain null. No address is synthesized from a name or institution.
- Public abstracts preserve source paragraphs. HTML subscript/superscript characters are converted to their Unicode text equivalents (for example, source `CO<sub>2</sub>` becomes `CO₂`) instead of discarding the source notation.

## Rate, session, and source-health constraints

No public PAMS rate-limit specification or structured service contract was found. The bounded reconnaissance did not encounter a 429 response, CAPTCHA, bot challenge, or login redirect on the award/abstract paths. Observed interactive responses ranged from roughly one second to about fifteen seconds, and PAMS displayed a scheduled-maintenance notice.

The production boundary is therefore intentionally conservative:

- no credential, login, or persistent session;
- one fresh form GET and one search POST per cache miss;
- at most ten normalized DOE results per product page;
- at most ten public-abstract GETs, concurrency two, with a short pause between batches;
- a bounded browse window through normalized offset 100;
- no automatic retry storm;
- the existing one-hour successful per-source Worker cache;
- validation of the PAMS form, grid, labeled fields, paging targets, official host, and matching public-abstract heading;
- per-abstract degradation when an individual document is unavailable;
- full DOE source isolation if the public search contract is unavailable or changes.

NSF and NIH use their existing adapters, requests, cache entries, and error paths. A PAMS failure cannot change or suppress their successful results.

## Production mapping decision

Current Funding Finder records receive a DOE funded-awards deep link only when both conditions hold:

1. the opportunity is controlled as DOE Office of Science (`PAMS-SC` / Office of Science); and
2. it carries an exact `DE-FOA-<number>` identifier accepted by the PAMS solicitation-number field.

Other DOE components (for example ARPA-E, NETL, and Idaho Field Office) are not treated as Office of Science awards. No fuzzy title or program equivalence is used. Standalone users can still run a controlled DOE abstract, institution, PI, program-area, program-manager, exact award, or exact FOA search.
