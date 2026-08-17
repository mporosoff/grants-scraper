# Source reachability sweep — 2026-08-17

**Every host this project had recorded as unreachable or blocked, re-tested with
the failure layer isolated.** Prompted by the NASA finding, and the first
application of §17.11.

**The headline: the NASA cause generalises to nothing.** Of 14 hosts, exactly
two were the TLS-cipher problem. The rest fail — or no longer fail — for four
other reasons, at four other layers. A single explanation was never available,
which is the point of isolating the layer rather than assuming.

## Method, and what was deliberately not done

Each host was walked **DNS → TCP → TLS → HTTP → application**. Two client
configurations only: the ordinary `PoliteClient`, and the per-adapter cipher
opt-in where TLS was implicated.

**Nothing here circumvents a restriction.** No browser user-agent spoofing, no
authentication, no anti-bot evasion, no header games to defeat a WAF. A
persistent `403` is recorded as an application-layer denial whose reason is not
visible from outside — it may be bot policy, geography, rate limiting, path
rules or something else — and it is left in place (§17.11).

## Results

| Host | Prior record | DNS | TCP | TLS | HTTP now | Diagnosis | Correction available |
|---|---|---|---|---|---|---|---|
| `nspires.nasaprs.com` | ConnectionReset ×12 | ok | ok | **FAIL default** | **200** with opt-in | **Client incompatibility** — cipher | ✅ shipped, narrow |
| `solicitation.nasaprs.com` | SSL EOF | ok | ok | **FAIL default** | **200**, 6,890 chars | **Client incompatibility** — cipher | ✅ shipped, narrow |
| `bja.ojp.gov` | 404 | ok | ok | ok | **200**, 4,214 chars | **Prior observation no longer reproduces** | none needed |
| `www.fema.gov` | 403 | ok | ok | ok | **200**, 15,031 chars | **Prior observation no longer reproduces** | none needed |
| `www.aphis.usda.gov` | ConnectionReset | ok | ok | ok | **200**, 7,722 chars | **Prior observation no longer reproduces** | none needed |
| `www.nrcs.usda.gov` | ConnectionReset | ok | ok | ok | **200**, 40,313 chars | **Prior observation no longer reproduces** | none needed |
| `www.transit.dot.gov` | 403 ×4 | ok | ok | ok | **403** | **Application-layer denial**, reason not visible | none — recorded, not circumvented |
| `www.rd.usda.gov` | 403 ×2 | ok | ok | ok | **403** | **Application-layer denial**, reason not visible | none — recorded, not circumvented |
| `www.nsf.gov/ods` | 404 | ok | ok | ok | **404** | **Dead URL**, not a reachability problem | fix the URL, not the client |
| `neup.inl.gov/SitePages/Home.aspx` | 404 | ok | ok | ok | **404** | **Dead URL** | fix the URL |
| `mygrants.servicenowservices.com` | "content-free JS shell" | ok | ok | ok | 200, **98 chars** | **Client-rendered app** — transport fine, content is JS | none at this layer |
| `portal.nyserda.ny.gov` | "JS shell / login wall" | ok | ok | ok | 200, **0 chars** | **Client-rendered app / credential wall** | none — intentional |
| `sam.gov` | "0 characters" | ok | ok | ok | 200, **11 chars** | **Client-rendered app** | none at this layer |
| `sfgrants.eda.gov` | "Salesforce shell" | ok | ok | ok | 200, **75 chars** | **Client-rendered app** | none at this layer |

## Five distinct failure layers, where the project had recorded one

| Layer | Hosts | Was the original diagnosis accurate? |
|---|---|---|
| **TLS cipher negotiation** | 2 | **No.** Recorded as the server resetting; it was our cipher list |
| **Transient, no longer reproduces** | 4 | **Partly.** The observation was real at the time; treating it as a permanent property was wrong |
| **Application-layer denial (403)** | 2 | **Yes as an observation**, but "403" names the layer, not the reason |
| **Dead URL (404)** | 2 | **Yes** — and it is a data-quality problem, not a reachability one |
| **Client-rendered app** | 4 | **Yes in substance.** Transport always worked; no bytes carrying content ever arrive |

**The four transient cases are the most instructive.** `fema.gov`, `aphis.usda.gov`,
`nrcs.usda.gov` and `bja.ojp.gov` all now return full pages with no client
change whatsoever. Their failures were real when observed and were recorded as
though they were properties of the source. **A single failed fetch, recorded
once, became a permanent fact in three documents.**

## What this changes, and what it does not

**Category (e) — "unreachable fetch path" — goes from 5 to 4**, and the
remaining four have corrected causes:

| Record | Was | Now |
|---|---|---|
| `360003` NASA ROSES A.10 | (e) unreachable | **(a)** — readable, and it is a single program element with no subdivisions of its own |
| `363296` BJA | (e) unreachable | **(e), cause corrected** — reachable, but it is a landing page and the solicitation is still one hop away, unmeasured |
| `355211` mygrants | (e) unreachable | **(e), cause corrected** — reachable; content is client-rendered |
| `nyserda:PON4924`, `nyserda:RFQL6152` | (e) unreachable | **(e), cause corrected** — reachable; credential wall / client-rendered |

So the miss-cause distribution moves **(a) 33 → 34, (e) 5 → 4**; the total of
53 non-accepting documents is unchanged.

**§1.1 is unchanged: ~171 records, 11.6%, band 54–538.** `360003` was already
counted as a non-hit in the survey's stratum-D denominator, so re-reading it
confirms an existing count rather than moving one. **No stratum rate, no
interval and no denominator changes.** Recording that plainly matters: the
sweep corrects *causes and classifications*, and it does not improve coverage.

**§12** keeps its agency-HTML row — four client-rendered apps confirm it — and
gains a transient-failure row (below).

**No newly reachable source is implemented in this session**, per scope.

## Preserved history

Where an artifact says a source was unreachable, the observation stands as what
the then-current client produced. What is corrected is the *conclusion* drawn
from it. The census, survey and taxonomy each now carry a banner distinguishing
the three:

1. **observed at the time** — the client failed, and that is what was recorded;
2. **corrected interpretation** — whether that failure established source
   unavailability (for NASA it did not; for the SPA hosts it effectively did);
3. **current re-test** — this table.
