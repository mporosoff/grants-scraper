# Offline AI model A/B test

## Scope

This benchmark compares OpenAI GPT-5.6 Luna with Cloudflare Workers AI Gemma 4 26B on the AI-assisted parts of Funding Finder:

1. **Enhance with AI**: alternative search phrases and candidate assessment
2. **Chat with results**
3. **Chat with NOFO**
4. **Ask about this institution**: question translation and bounded narrative synthesis

The existing evaluation export is optional background evidence only; no additional feedback exports are required for this benchmark.

## Safety and cost controls

- The benchmark Worker is separate from the live site and has no live-site route.
- Every request requires a private bearer token; there is no browser CORS access.
- The Worker stores neither prompts nor responses and sends `store: false` to OpenAI.
- Provider outputs are capped at 5,000 tokens and provider requests at 60 seconds.
- Invalid structured output receives at most one retry.
- Cloudflare applies a 60-request-per-minute account-side limit.
- The runner defaults to estimate-only mode. It cannot make a provider call unless `--run` is supplied.
- Results and review artifacts are written under the git-ignored `evaluation/ai-model-results/` directory.

## One-time setup

Wrangler must be logged into the intended Cloudflare account. Store the OpenAI key only with Wrangler's hidden prompt:

```powershell
pnpm dlx wrangler secret put OPENAI_API_KEY --config workers/ai-benchmark/wrangler.jsonc
```

Do not paste the key into chat, a command argument, `wrangler.jsonc`, source code, or a committed file.

The separate `BENCHMARK_TOKEN` is machine-generated during setup. It is not the OpenAI key and should not be shared.

## Test cases and review

The committed suite contains six focused cases, one for each production structured-response contract. Every case runs three times per model by default, for 36 total requests. Requests are interleaved in a seeded random order.

The runner saves after every response and can resume the same exact configuration. When all calls finish it creates:

- `results.json`: model-labelled outputs, latency, usage, retry count, and automated checks
- `blind-review.json`: paired responses labelled only A and B for human review
- `blind-key.json`: the A/B identity key, to be opened only after review

Human review asks for a preference plus 1–5 scores for factual grounding and usefulness. The default review contains six short A/B pairs—one per contract—while the other runs measure consistency automatically. It covers the four priority features rather than ordinary search.

## Commands

Estimate calls, tokens, and usage price without contacting either provider:

```powershell
pnpm benchmark:ai
```

Run only after the Worker endpoint and private token are configured and the estimate is accepted:

```powershell
pnpm benchmark:ai -- --run --endpoint https://funding-finder-ai-benchmark.ACCOUNT.workers.dev
```

`BENCHMARK_TOKEN` must be supplied through the process environment, never as a command-line argument. The setup operator handles this without displaying the token.
