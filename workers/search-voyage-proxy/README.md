# Funding Finder Voyage search proxy

This Worker exposes only two POST endpoints:

- `/embed-query` for a bounded public Funding Finder query;
- `/rerank` for up to 300 passages whose IDs and SHA-256 hashes match the
  generated current or immediately previous public corpus allowlist.

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

## Local verification

Create an ignored `.dev.vars` file in this directory containing
`VOYAGE_API_KEY=...`, then run:

```powershell
npx wrangler dev
```

Never commit `.dev.vars` or an API key.

## Deployment

From this directory, authenticate Wrangler, set the encrypted secret, and
deploy:

```powershell
npx wrangler login
npx wrangler secret put VOYAGE_API_KEY
npx wrangler deploy
```

Production deployment is owned by the coordinated refresh workflow after its
vector, package-integrity, Python, browser, and search-quality gates pass. A
manual deployment must follow the same order and must never publish a Worker
that lacks compatibility with the currently live Pages corpus.
