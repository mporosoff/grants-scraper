# Funding Finder Voyage search proxy

This Worker exposes only two POST endpoints:

- `/embed-query` for a bounded public Funding Finder query;
- `/rerank` for up to 300 passages whose IDs and SHA-256 hashes match the
  committed public passage manifest.

The Worker does not log query strings, accept researcher profiles/CVs/ORCID
data, return documents, or expose the Voyage credential. Browser requests are
accepted only from `https://mporosoff.github.io` and local HTTP development
origins. Embedding/reranking failures return bounded error codes so the browser
can retain the local Strong matches and omit unavailable Potential matches.

## Local verification

Create an ignored `.dev.vars` file in this directory containing
`VOYAGE_API_KEY=...`, then run:

```powershell
npx wrangler dev
```

Never commit `.dev.vars` or an API key.

## One-time deployment when separately authorized

From this directory, authenticate Wrangler, set the encrypted secret, and
deploy:

```powershell
npx wrangler login
npx wrangler secret put VOYAGE_API_KEY
npx wrangler deploy
```

After deployment, put the resulting Worker base URL in the non-secret browser
configuration, add that exact HTTPS origin to the page's `connect-src` policy,
rerun development/acceptance gates, and only then consider enabling search v2.
This repository session does not run these commands.
