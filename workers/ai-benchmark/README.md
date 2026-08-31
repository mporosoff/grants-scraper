# Private AI model benchmark Worker

This Worker is an offline evaluation harness for Funding Finder. It is not used by the live site.

It exposes an authenticated endpoint for the six existing structured AI operations and compares:

- OpenAI `gpt-5.6-luna` through the Responses API
- Cloudflare Workers AI `@cf/google/gemma-4-26b-a4b-it`

Prompts and responses are not logged or stored by the Worker. The local runner saves checkpoints under the git-ignored `evaluation/ai-model-results/` directory. Requests are limited to 30 per minute, outputs are bounded, both providers receive the same production response schemas, and malformed structured output gets at most one retry.

Required Cloudflare secrets:

- `OPENAI_API_KEY`
- `BENCHMARK_TOKEN`

Never put either value in this file, `wrangler.jsonc`, a shell command, or a committed environment file. Use Wrangler's hidden secret prompt.
