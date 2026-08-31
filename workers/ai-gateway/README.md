# Funding Finder hosted AI gateway

This Worker powers the optional hosted AI features without exposing a provider key in the browser.

The browser sends only a supported operation name and its bounded user payload. The Worker owns the production prompts, schemas, and model routing:

- Gemma: search phrase expansion and institution-question translation
- GPT-5.6 Luna: candidate assessment, results chat, and institution narrative
- NOFO chat: Luna first for consistent structured presentation, with Gemma as the bounded fallback

The Worker does not log or store prompts or responses. OpenAI requests set `store: false`; request and output sizes are bounded; client and global request rates are limited; browser origins are allowlisted; and every response is validated against the operation schema.

`OPENAI_API_KEY` is the only required secret. Add it with Wrangler's hidden secret prompt. Never put it in this file, the Worker configuration, a shell command, a committed environment file, or the public site.
