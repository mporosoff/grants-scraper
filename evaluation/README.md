# Phase 2 evaluation workflow

The human Phase 2C pilot is deferred until the Phase 3 source-evidence
deployment gate passes. See `PHASE3_REVIEW.md` for the current explicit file
handoff, private inbox, and reporting workflow.

Open the dedicated pilot route by adding `?evaluation=1` to Funding Finder's
URL. Normal search does not show rating controls. In evaluation mode, Funding
Finder keeps pilot ratings on the researcher's device. A participant
can label result cards as `not relevant`, `partial`, `useful`, `strong`, or
`needs verification`, optionally choose a reason, and explicitly export one
JSON file.

The export intentionally excludes:

- API keys;
- CV text and the original CV file;
- the research description and expertise text; and
- chat messages.

It includes a non-content comparison fingerprint, catalog timestamp, public
opportunity metadata, the current search text, active filters, retrieval rank,
AI rank, provider/model, prompt version, and reason codes. Because search text
can itself describe research, participants must use non-confidential wording
they are comfortable returning to the pilot team. Researchers should review
the exported file before sharing it.
The fingerprint is only for comparing profile versions within the pilot; it
is not a secure identity or authentication mechanism.

Start each participant/session with cleared labels, label both the AI shortlist
and the “Review retrieved candidates” view, then export once. The evaluator
uses the exported candidate identifiers—not only displayed rank—to determine
candidate-set membership.

The old “Personalize from my ratings” product experiment is retired for v1.
Pilot labels remain measurement evidence only and never alter search ranking.

## Aggregate a pilot

Run the versioned evaluator over one or more consented exports:

```powershell
python -m scripts.evaluate_phase2 path\to\export-1.json path\to\export-2.json
```

Add `--json` for machine-readable output. The evaluator reports:

- useful-opportunity recall within the 32-record retrieval set;
- useful-result precision within the AI top 12;
- mean rank movement from retrieval to AI order;
- eligibility error rate; and
- expired/closed error rate.

The synthetic regression fixture is
`tests/fixtures/phase2_evaluation_export.json`. It tests the evaluator's math
but is not pilot evidence. Phase 2 is complete only after consented labels from
3–5 researchers are aggregated and a short pilot report documents retrieval,
reranking, and source-data failures separately.

## Reproduce the profile-ranking probe

The deterministic probe compares the reported catalyst/AI query with no
profile, the screenshot profile, and that profile plus a representative CV. It
also measures how many profile-only candidates survive each concept-coverage
threshold:

```powershell
node evaluation/profile_relevance_probe.mjs
```

Rank movement proves that profile fields affect production scoring; it does not
prove that the movement is better. Treat the probe as a regression and
diagnostic. Precision/recall benefit still requires the consented human labels
described above.
