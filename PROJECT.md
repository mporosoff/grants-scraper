# UR ChemE Grant Matching System

**Status:** private web pilot; complete workflow validated with live Grants.gov data
**Initial scope:** Department of Chemical and Sustainability Engineering
**Last updated:** July 2026

---

## 1. What this is

A system that pulls funding opportunities from federal sources, normalizes them
into a schema built for screening decisions, and pairs each one with the
research-active faculty most likely to be competitive for it.

The intent is not another searchable list. Searchable lists already exist and
are largely unused. The intent is a ranked, explained, push-based
recommendation that answers a specific question: is this worth my time?

Faculty create and maintain their own profiles through the web application.
This avoids a brittle dependency on department-page scraping, gives researchers
control over how their work is represented, and makes the system reusable
outside a single department.

---

## 2. What we have done

### 2.1 Surveyed the existing landscape

**Duke's Research Funding database** (researchfunding.duke.edu) was reviewed as
the closest public comparable. It is a curated Drupal site with faceted search
by agency, discipline, and eligibility, plus a Monday newsletter and saved
searches. Identified weaknesses:

| Weakness | Consequence |
|---|---|
| Maintained by hand by the Office of Research Initiatives | Up to a week of lag between agency posting and visibility |
| No faculty pairing of any kind | The user does all the filtering themselves |
| Faceted browse sorted by agency name, 400+ result pages | No relevance ranking, so no triage order |
| Discipline taxonomy is coarse and clinically weighted | A single "Engineering" bucket cannot separate catalysis from photonics |
| One deadline field | Multi-stage programs collapse into a single date |
| Eligibility as one flat facet | Career stage, PI rank, and citizenship are distinct axes |
| Award economics not structured | Cannot filter on ceiling, award count, or cost share |
| Login-gated, no export, no API, robots-disallowed | Nothing composable |

### 2.2 Found and studied a failed precedent

The most useful source was not a vendor page. SUNY Albany built essentially
this system, called **Research Highlighter-MatchMaker**, and published the
results including negative feedback (NSF PAR 10566919).

Their stated motivation matches ours. NIH approval rates fell from over 30
percent in 2000 to roughly 17 percent, and by some estimates top researchers
spend half their time writing grants.

Their critique of Pivot and SPIN: keyword-match recommendations miss grants
that lack the matched keyword, and the systems ignore personal research track
records, so faculty end up searching manually anyway.

**Their method, and why it failed.** They used exact string matching against
SPIN's keyword hierarchy, scored as occurrence count times a first-author
weight times matched-document fraction. Pilot feedback included:

> The recommendations had nothing to do with my research.

> Suggestions have not been aligned with my research interests and areas of
> expertise at all. It might be helpful to ask for keywords aligned with our
> research interests to better tailor suggestions.

Two design requirements follow directly, and both are non-negotiable:

1. **Semantic matching, not string matching.** "CO2 hydrogenation" and "carbon
   dioxide reduction" must match. Exact string comparison cannot do this.
2. **Faculty-editable profiles with visible rationale.** Every match must show
   why it matched, and the PI must be able to correct the profile. This was
   Albany's single most requested fix.

### 2.3 Established the screening schema

Fields a PI actually needs to decide whether to pursue. Grouped by purpose.

**Identity**
opportunity number, title, agency and sub-office, ALN, detail page URL, NOFO
PDF URL, version and amendment date

**Dates, as separate fields rather than one**
posted date, LOI deadline, concept paper deadline, preproposal deadline, full
proposal deadline, **deadline clock time and timezone**, anticipated award
date, project start date, rolling flag, internal UR deadline

**Money**
award ceiling, award floor, total program funding, expected number of awards,
project duration, **cost share requirement and percentage**

**Eligibility**
applicant type, career stage with years-since-PhD, PI rank requirement,
citizenship, required partners, **limited submission limit and criteria**

**Judgment**
program officer name and email, topic areas within the FOA, page limit, review
criteria, required documents, whether a preproposal gate exists

Indirect cost cap was considered and **deliberately excluded** per direction:
UR weights prestige above recovery rate, so it is not a screening factor here.

### 2.4 Built the first ingestion prototype

The original prototype included **`scrape_faculty.py`**, which read the Core
Faculty listing and assembled profiles from department pages. That approach has
been retired. The script remains under `legacy/` as a reference, but it is not
part of the product roadmap.

**`scripts/pull_grants.py`** queries the public Grants.gov REST API. search2
and fetchOpportunity require no authentication. It searches across a keyword
list, de-duplicates, fetches full detail, and normalizes into the schema above.
It also runs a regex library over the free-text description to extract the four
fields Grants.gov does not structure: limited submission limits, cost share
percentages, concept paper and preproposal deadlines, and deadline clock time
with timezone.

The extraction patterns were verified offline against real solicitation
phrasing from ARPA-E, NSF, and DOE, including NSF's awkward
`5:00 p.m. submitter's local time`.

### 2.5 Built the first usable web workflow

The `web/` application now implements the core faculty experience: an editable
research profile, durable application storage, live Grants.gov refresh,
normalized JSON import, ranked and explained matches, eligibility warnings,
saved useful/not-relevant feedback, and filtered CSV export.

`match_explorer.html` was useful as an interaction prototype. Its strongest
ideas—the shortlisting view, verdicts, rationales, source links, and export—are
now part of the hosted application. Its direct browser API-key fields and
bundled scraped faculty records were intentionally not carried forward.

The deployed matcher is still a transparent lexical baseline. It exists to
make the entire product testable before introducing a more expensive semantic
stage.

---

## 3. What we really intend to build

Stage 1 is a data pipeline. The actual product begins with the profile and
matching experience in stages 2 through 6.

### Stage 2: Faculty-authored research profiles

Each faculty member creates a profile through a short web form. The core input
is a research synopsis in the faculty member's own words, supplemented by
structured topics, methods, application areas, career stage, and optional
exclusions. Profiles remain editable at all times.

This is more adaptable and more accurate than inferring identity and interests
from department pages. **OpenAlex** may later suggest topics or enrich a profile
from recent publications, but publication data is optional and never overrides
what the faculty member has written.

### Stage 3: Semantic matching with visible rationale

Embed faculty profiles and opportunity descriptions, retrieve candidates by
vector similarity, then re-rank the top candidates with an LLM that outputs a
score plus a one-sentence rationale naming the specific overlap.

Two-stage design is deliberate. Embeddings are cheap and handle the wide funnel.
LLM scoring is expensive and only runs on plausible candidates. Every match
carries its rationale, and every profile is editable.

### Stage 4: NOFO PDF parsing

Grants.gov keyword search matches only title, description, and agency name. It
does not index attachments. Everything stated only inside the PDF is invisible
to search, and that includes most of what determines whether a proposal is
worth writing.

Plan: download the NOFO PDF, extract text, and parse page limits, review
criteria, required documents, cost share terms, and limited submission
language. Surface the PDF one click from every dashboard row, and store the
parsed fields alongside the API fields with clear provenance on which came from
where.

### Stage 5: Source expansion

Grants.gov is the right backbone. NIH consolidated onto it in FY2026 and no
longer posts NOFOs to the NIH Guide. But it is not complete.

| Missing source | Why it matters | Access route |
|---|---|---|
| ARPA-E eXCHANGE | ARPA-E does not use the standard Grants.gov process; concept papers are the stage that needs early warning | arpa-e-foa.energy.gov, scrape |
| DOE Office of Science | FOA posts to science.osti.gov, preproposal runs through PAMS, only the full proposal reaches Grants.gov | science.osti.gov, scrape |
| DOD and DARPA BAAs | Posted as contracts on SAM.gov, which has no saved-search alerts as of Feb 2026 | SAM.gov API |
| Private foundations | ACS PRF, Sloan, Moore, Simons, Dreyfus, Beckman, Keck, Research Corporation. A large fraction of realistic ChemE targets | Individual scrapers, no common feed |
| Corporate programs | Toyota, Dow, 3M, Amazon Research Awards | Individual, mostly manual |
| NSF Dear Colleague Letters | Often never reach Grants.gov | nsf.gov, scrape |
| Limited submission designations | Institutional by nature, absent from every federal feed | UR Office of Research, manual |

### Stage 6: Delivery

Searchable dashboard plus Excel export. Weekly push digest per faculty member,
because Albany's data shows push works and pull does not. Faculty profile
editing UI. Scheduled nightly pull.

---

## 4. Limitations of the current approach

This section is the honest one. Read it before showing this to anyone.

### 4.1 Live validation is still narrow

The Grants.gov script was smoke-tested against live posted and forecasted
opportunities on July 25, 2026. The test reconciled the synopsis and forecast
field families, verified attachment downloads, and normalized a small set of
NSF, Army, Air Force, and HHS records.

This is not yet production coverage. Agencies use the optional fields
inconsistently, attachment folders can contain amendments and supporting
documents, and the test set is too small to establish completeness. Raw
responses should continue to be retained during development for regression
testing.

### 4.2 Regex extraction is triage, not ground truth

The four fields extracted from free text (limited submission, cost share,
preliminary deadlines, timezone) come from pattern matching over prose written
by dozens of different agencies with no style guide. This will produce both
false positives and false negatives.

**These fields should be treated as flags that send a human to the PDF, never
as authoritative values.** A missed limited-submission flag means a wasted
proposal. Design the UI so the flag links to the source text it matched on.

### 4.3 Match quality is the actual hard problem, and it is not yet validated

Everything above is plumbing. Albany's system worked mechanically and still
drew "the recommendations had nothing to do with my research." Semantic
matching improves on string matching but does not guarantee usefulness.

The web application now captures useful/not-relevant judgments, but there is
not yet a sufficiently large evaluation set. We need a few dozen labeled
opportunity-faculty pairs before claiming that semantic changes improve the
recommendations. Without that, tuning remains guesswork.

### 4.4 Scraping is structurally fragile

Every non-API funding source in stage 5 is a separate scraper with its own
failure mode, and those integrations will eventually break as source sites are
redesigned. Faculty profiles are deliberately excluded from this scraping
dependency.

Mitigation: the pipeline should fail loudly with row-count checks, not fail
quietly with empty output.

### 4.5 Some required data is not obtainable programmatically

Limited submission designations, internal UR deadlines, and institutional
eligibility rulings exist only inside the UR Office of Research. No amount of
scraping produces them. Either that office participates or those fields stay
partly empty.

### 4.6 Maintenance burden is the most likely cause of death

Duke staffs its database with an office. Albany ran theirs out of a dedicated
Office of Strategic Initiatives with a director and a data analyst. This
project currently has neither.

A nightly pipeline with seven scrapers, an LLM matching stage, and PDF parsing
will need real attention. Plan for who owns it after the novelty wears off, or
scope it down to Grants.gov plus one or two high-value scrapers that can be
maintained by one person.

### 4.7 Legal and cost notes

- **Do not scrape Pivot-RP.** It is a Clarivate subscription product and
  automated access violates the terms. UR almost certainly holds a license for
  manual use.
- Grants.gov data is public federal information with no usage restriction.
- LLM re-ranking has a per-opportunity cost. At a few hundred opportunities
  times fourteen faculty, this is small, but it scales with any expansion to
  the full Hajim School.
- LLM-generated rationales can be confidently wrong. They are a reading aid,
  not evidence.

### 4.8 Honest note on the ambition

The goal stated at the outset was for this to be the premiere system for grant
searching and identification. Worth being clear about what stands between here
and there.

The code is the easy part. What makes Pivot valuable is not its software, it is
a paid editorial team maintaining eligibility and deadline accuracy across
thousands of sponsors. What would make this system better than Pivot for UR
specifically is not breadth, it is two things Pivot structurally cannot do:
faculty-controlled profiles tuned for recommendation quality, and institutional
knowledge like limited submission slots and internal deadlines.

Compete on depth for fourteen people, not breadth across four thousand
sponsors. That is a winnable fight.

---

## 5. Immediate next steps

1. Pilot the hosted workflow and label a small, representative set of good and
   bad faculty-opportunity pairs.
2. Add server-side embeddings for candidate retrieval and an explainable
   semantic reranker; keep all model credentials out of the browser.
3. Compare semantic results against the lexical baseline and the labeled set.
4. Add scheduled opportunity refresh plus stale/deadline monitoring.
5. Parse NOFO PDFs for review criteria, required documents, and eligibility
   details that are missing from Grants.gov fields.

## 6. Files

| File | Purpose |
|---|---|
| `web/` | Hosted application, APIs, D1 schema, migrations, and tests |
| `match_explorer.html` | Original static interaction prototype |
| `legacy/scrape_faculty.py` | Retired faculty scraper retained for reference |
| `scripts/pull_grants.py` | Grants.gov API puller and normalizer |
| `README.md` | Run instructions and setup |
| `PROJECT.md` | This document |

## 7. Sources consulted

- Duke Research Funding database, researchfunding.duke.edu
- SUNY Albany, Research Highlighter-MatchMaker, NSF PAR 10566919
- Grants.gov API guide, grants.gov/api/api-guide
- NIH NOT-OD-25-143 on Grants.gov consolidation
- ARPA-E eXCHANGE, arpa-e-foa.energy.gov
- UR ChemE Core Faculty listing, hajim.rochester.edu/che/people/faculty
