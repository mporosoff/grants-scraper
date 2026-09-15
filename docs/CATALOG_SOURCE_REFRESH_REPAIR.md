# September 15 catalog source repair

The public catalog is September 11 data. September 14's candidate (PR249,
`f56721d3e6bd4db720604414994614aa471b4d250b241f6e05dcc10fb1b76673`)
failed publication and subsequently received two consequential source findings.
September 15's scheduled run34985535113 generated another candidate
`ebbfe144a0978a1807c899856e84d426237f458e36250d1653632ee67ae0d0ba`
(PR253), retaining those source errors. It stopped before any serving change:
the Actions bot's review request was declined by the connector, then the
publication review wait expired. Generation succeeded; public publication did not.

This repair recognizes the sponsor on the official NSF feed's own HTTPS funding
links. Previously the adapter omitted the agency, so canonicalization marked
NSF as an aggregator default and the correct sponsor-scoped duplicate guard
could not join its rows to Grants.gov. The existing merger continues to keep
the Grants.gov identity and facts, preserve the alternate official links as
source aliases, and record conflicting facts rather than override them.
Program description identifiers retain `PD` and their full suffix; different
solicitation editions remain distinct. Generic RSS feeds gain no sponsor authority.

VPR applicant-directed prose can no longer open an opportunity buffer, including
a sentence that ends with a link lead-in rather than a full stop. It remains
inside the preceding call so its deadline does not move into a fictitious card.
The existing publication filter also rejects a previously cached VPR fragment,
including `vpr-email:vpr-7921302c954613de`.

The confirmed source equivalences are Grants.gov350802 / NSF24-503 and
Grants.gov334326 / NSF21-595. Their official program pages identify the same
guidelines: [RET](https://www.nsf.gov/funding/opportunities/research-experiences-teachers-engineering-computer-science)
and [TCUP](https://www.nsf.gov/funding/opportunities/tcup-tribal-colleges-universities-program).
The real NSF feed was retrieved once at 2026-09-15T15:52:37.692120Z:
11,697 bytes, SHA256`ad9f19176c2d9c3fd6b9c0b7fd3910cbfb8ee5599e5d8baceae0f139733fbcdc`,
12 entries; all 12 now have the feed's authoritative sponsor and complete number.

Other repeated-number records are audited separately. A VPR heading, number or
generic agency link alone is not silently promoted to verified sponsor identity.
Those unresolved source comparisons must remain visible in the release report;
they are not proof that every repeated number is a duplicate. No similarity-based
collapse, source-date invention or researcher/team requalification is introduced.

Validation: 95 focused source/parser/lifecycle tests pass, including exact IDs,
retained evidence/conflicts, idempotence, program-code/successor separation,
untrusted URLs, HTML/plain digest segmentation and cached-fragment filtering.
Required exact-head CI and independent review remain publication gates. No
E2E/Playwright run is required or initiated by this source-only repair.

Publication must use a corrected, preserved candidate through the existing
immutable release lifecycle. Neither held candidate is silently modified or
approved. A connected maintainer must initiate the actual candidate's review:
the current Actions bot has no working Codex connection. Do not reuse researcher
publication credentials for catalog review, bypass review, or represent a
successful source build as a public update. Researcher registry activation and
the contextual/Luna scientific checker are separate boundaries.
