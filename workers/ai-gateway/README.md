# Funding Finder hosted AI gateway

This Worker powers the optional hosted AI features without exposing a provider key in the browser.

The browser sends only a supported operation name and its bounded user payload. The Worker owns the production prompts, schemas, and model routing:

- Gemma: search phrase expansion, institution-question translation, and Program Officer question planning
- GPT-5.6 Luna: candidate assessment, results chat, institution narrative, and Program Officer evidence synthesis
- NOFO chat: Luna first for consistent structured presentation, with Gemma as the bounded fallback

The Worker does not log or store prompts or responses. OpenAI requests set `store: false`; every operation has an exact bounded input contract; request and output sizes are bounded; browser origins are allowlisted; and every response is validated against the operation schema.

Two independent controls protect the site-managed provider balance. Cloudflare rate-limit bindings cap client and global requests per minute. A Durable Object atomically applies weighted per-client and global daily budgets before a provider call. The daily state contains only a UTC date, counters, and SHA-256 client identifiers; it never contains prompt or response text. `AI_GATEWAY_ENABLED=false`, missing budget configuration, or an unavailable budget binding disables provider calls rather than bypassing the controls.

The committed daily unit limits are conservative weighted token-equivalent ceilings, not billing estimates. Luna routes carry a higher weight, and each pre-call unit charge covers the bounded retry and fallback paths. Change them only through a reviewed deployment:

- `AI_DAILY_CLIENT_UNIT_BUDGET`
- `AI_DAILY_GLOBAL_UNIT_BUDGET`
- `AI_BUDGET_RETRY_AFTER_SECONDS`

`OPENAI_API_KEY` is the only required secret. Add it with Wrangler's hidden secret prompt. Never put it in this file, the Worker configuration, a shell command, a committed environment file, or the public site.
