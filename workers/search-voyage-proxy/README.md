# Funding Finder Voyage search proxy

This Worker exposes two POST endpoints and one bounded health endpoint:

- `/embed-query` for a bounded public Funding Finder query;
- `/rerank` for up to 300 passages whose IDs and SHA-256 hashes match the
  generated current or immediately previous public corpus allowlist;
- `GET /health` for service, current-corpus, compatibility-window, coarse
  budget availability, and bounded aggregate reserved-token totals only.

The Worker does not log query strings, accept researcher profiles/CVs/ORCID
data, return documents, or expose the Voyage credential. Browser requests are
accepted only from `https://mporosoff.github.io` and local HTTP development
origins. Embedding/reranking failures return bounded error codes so the browser
can retain the local Strong matches and omit unavailable Potential matches.

`tools/build_search_release_package.mjs` generates the allowlist from the
validated semantic manifest. The scheduled refresh deploys this compatibility
Worker before committing the matching catalog, manifest, vectors, and release
metadata, so old and new browser generations can coexist while Pages updates.
Every next successful refresh retires the older of the two generations.

## Abuse and cost controls

The Worker fails closed unless all production settings and bindings are valid.
The committed initial ceilings are:

- 12 embedding requests and 8 reranking requests per client per minute;
- 600 hosted-search requests globally per minute;
- 50,000 embedding input tokens per UTC day;
- 25,000,000 reranking input tokens per UTC day;
- a bounded 10-second `Retry-After` on `429` responses.

Cloudflare rate-limit bindings enforce the short windows. One SQLite-backed
Durable Object coordinates exact daily reservations and stores only aggregate
request counts, provider input tokens, failures, rejection counts, and latency
histograms. It never receives or stores query strings, passages, researcher
names, ORCID/CV/profile content, or IP addresses. The per-client IP is used only
as the ephemeral Cloudflare rate-limit key.

Reservations expire after 30 seconds, safely beyond the seven-second provider
timeout. Expired reservations are pruned on every coordinator action, and both
admission decisions and the bounded health state count only unexpired reserved
tokens.

`ENHANCED_SEARCH_ENABLED=false` is the global semantic-search circuit breaker.
A missing/invalid budget, rate binding, counter binding, or provider key returns
`503` without contacting Voyage. Budget or rate exhaustion returns `429` before
any provider request.

## Local verification

Create an ignored `.dev.vars` file in this directory containing
`VOYAGE_API_KEY=...`, then run:

```powershell
npx --yes wrangler@4.125.0 dev
```

Never commit `.dev.vars` or an API key.

## Deployment

From this directory, authenticate Wrangler, set the encrypted secret, and
deploy:

```powershell
npx --yes wrangler@4.125.0 login
npx --yes wrangler@4.125.0 secret put VOYAGE_API_KEY
npx --yes wrangler@4.125.0 deploy
```

Production deployment is owned by the coordinated refresh workflow after its
vector, package-integrity, Python, browser, and search-quality gates pass. A
manual deployment must follow the same order and must never publish a Worker
that lacks compatibility with the currently live Pages corpus.
