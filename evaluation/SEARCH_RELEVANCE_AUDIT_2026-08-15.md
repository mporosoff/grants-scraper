# Search relevance audit: catalyst + AI report

Date: 2026-08-15
Catalog: 1,469 current opportunities, `catalog-20260815T183714Z`
App version after fix: `search-relevance-v4`

## Reported case

- Query: `catalysts for AI`
- Research description: `We do electrochemistry and can develop well-controlled colloids`
- Expertise: `Catalysis, AI, chemical engineering`
- Applicant context: college or university
- Observed false positives: AI journalism in Ukraine (`363440`) and the
  EducationUSA AI roadshow in Iraq (`363547`)

## Root-cause evaluation before the change

The production scorer expanded the reported query to two concept groups,
`catalyst` and `ai`, but set `minimumCoverage` to zero. Any record matching
either word entered the candidate set. The enabled profile affected ranking but
was not an admission constraint.

Three independent failures compounded:

1. Two-concept queries behaved as OR queries. The reported query returned 864
   records (58.8% of the catalog); 82 had any lexical query evidence, while the
   rest were admitted through inferred topics.
2. Corpus-derived topic feedback acted as candidate generation. Six literal
   uses of `catalyst` inferred broad topics and expanded a catalyst-only search
   to 417 records. This is query drift, not semantic matching.
3. `catalyst` did not recover `catalysis` or `catalytic`. The system therefore
   missed stronger chemistry wording while retaining metaphorical uses such as
   “a catalyst for education” and the product name BioData Catalyst.

A separate classifier defect assigned `Arts and culture` to many AI notices
because the `art` regular expression also matched the beginning of
`artificial`. That polluted facets and made topic feedback still less reliable.

## Design research

- Elasticsearch exposes `minimum_should_match` specifically to control how
  many analyzed query clauses a document must satisfy, while keeping synonyms
  inside their clause: <https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-match-query>
- Azure AI Search applies semantic ranking as a second stage over an initial
  BM25/RRF result set; it does not use the reranker to indiscriminately turn a
  coarse category into candidates: <https://learn.microsoft.com/en-us/azure/search/semantic-search-overview>
- Azure's agentic retrieval broadens or revises a query only after a
  high-precision classifier judges the first pass insufficient, and keeps the
  semantic candidate set bounded: <https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-set-retrieval-reasoning-effort>
- A TREC genomics study found that pseudo-relevance feedback degraded retrieval
  when too many feedback documents were used; a small, query-biased feedback
  set performed better: <https://trec.nist.gov/pubs/trec15/papers/umass.geo.final.pdf>

These patterns support a precision-first lexical gate, controlled within-group
synonyms, and bounded second-stage reranking.

## Implemented policy

- One concept requires one lexical concept match.
- Two concepts require both.
- Three or more concepts require 60%, rounded up.
- Exact title/opportunity-number matches retain their bypass and priority.
- Catalog topics can rerank admitted lexical candidates but cannot create new
  candidates.
- `catalyst`, `catalysis`, `catalytic`, and electro/photo/thermocatalysis are
  one guarded scientific concept. A bare `catalyst` must occur near chemistry,
  reaction, reactor, catalyst-design, or related scientific evidence.
- `AI`, `artificial intelligence`, and `machine learning` are alternatives
  inside one concept group, preserving recall without weakening cross-concept
  coverage.
- Known multiword scientific names (for example, `perfluorooctanoic acid`) stay
  one concept rather than becoming accidental AND constraints.

The browser scorer and saved-search/email scorer use the same policy.

## Post-change result

The reported query returns 12 records (0.82% of the current catalog), down from 864.
The four explicitly labeled false positives below are excluded:

| Opportunity | Failure type | After |
| --- | --- | --- |
| AI journalism in Ukraine (`363440`) | AI only | Excluded |
| EducationUSA AI roadshow (`363547`) | AI only | Excluded |
| NExT AI learning hubs (`359949`) | Metaphorical catalyst | Excluded |
| NHLBI TOPMed (`359942`) | BioData Catalyst product name | Excluded |

Recall guards remain for Chemical Process Systems (`362061`), the DOE Office
of Science umbrella (`360678`), and NSF Chemistry Disciplinary Research
Programs (`347749`).

## Broad-call recall guard

The coverage gate is intentionally not bypassed for every BAA. Opaque umbrella
notices instead receive searchable program scope at catalog-build time only
when a stable notice identifier or a scoped agency/title conjunction matches an
audited registry rule. The added scope retains its official evidence URLs.

This mechanism covers more than the reported catalyst wording. The current ONR
Long Range BAA (`N0001425SB001`) gains catalog evidence for catalysis,
electrochemistry, materials and separations, AI/ML, energy, and quantum science
from ONR program pages that explicitly direct proposals to that BAA. DOE
`DE-FOA-0003600` remains discoverable through the same registry architecture.
An unrelated record containing only the generic phrase “Broad Agency
Announcement” receives no augmentation.

On the refreshed catalog (1,475 total records; 1,469 currently open or
forecasted), `catalysts for AI` returns 12 records and includes both DOE
`DE-FOA-0003600` and ONR `N0001425SB001`. Catalyst-only returns 13;
electrochemistry returns 2 (the DOE and ONR umbrellas); quantum materials
returns 14 and includes both; selective extraction returns the ONR BAA. The
matrix is intentionally broader than the reported term.

The cross-domain audit also found a separate raw-substring defect: the `EERE`
registry trigger matched “engineered.” Four NSF engineering records had
inherited renewable-energy terms. Acronym triggers now require whole tokens,
the four stale catalog contributions were removed, and registry contributions
are reversible if a future rule changes or is retired.

This is a reproducible regression evaluation, not a claim of population-level
precision or recall. A full measurement still requires the planned labeled
researcher pilot; the new production-catalog tests prevent this specific class
of leakage while that evidence is collected.

## Profile and added-latency evaluation

The researcher inputs are part of the production score, not display-only
fields. The explicit query remains the admission gate; research description,
expertise, CV/ORCID terms, applicant type, and career stage then add independent
ranking evidence inside that candidate set. The optional AI refinement also
receives a bounded profile/CV excerpt and at most 32 retrieved candidates.

The reproducible `evaluation/profile_relevance_probe.mjs` run found:

- `catalysts for AI` admitted the same 12 candidates with or without the
  screenshot profile, confirming the profile cannot reopen irrelevant
  query-only records;
- the profile supplied six concrete catalog concepts and materially changed
  per-record scores;
- adding a representative electrochemical-catalysis CV changed the order (for
  example, NSF Transport Phenomena moved from rank 4 to rank 2), confirming
  that CV text is active ranking evidence; and
- under the former one-term profile-only admission rule, the screenshot profile
  admitted 541 current records. Requiring three of its six independent concepts
  reduced that to 19 while retaining all four audited recall anchors: NSF CPS,
  NSF Chemistry, DOE `DE-FOA-0003600`, and ONR `N0001425SB001`.

The profile extractor now suppresses generic CV verbs and counts synonym
variants as one concept, so `AI`/`artificial intelligence` cannot satisfy
multiple profile-only requirements by itself. Richer profiles use a bounded
50% concept floor (maximum four) rather than a fixed one-term match.

No artificial 1–2 second delay was added. Local second-stage reranking is cheap;
the probe's median was 2.5 ms for query-only ranking, 8.6 ms with the screenshot
profile, and 22.0 ms with the representative CV. Waiting by itself cannot
improve relevance. A slower model-based reranker can help only if measured
against labeled judgments. The existing optional AI pass
is the appropriate bounded experiment, and the Phase 2 export/evaluator already
separates 32-candidate recall from top-12 AI precision so the pilot can show
whether its extra latency produces a real quality gain.
