(() => {
  "use strict";

  const OPENAI_MODEL = "gpt-5.6-luna";
  const ANTHROPIC_MODEL = "claude-sonnet-5";
  const MAX_OUTPUT_TOKENS = 5000;
  const MAX_JSON_ATTEMPTS = 2;

  function extractJson(text) {
    const cleaned = String(text || "")
      .trim()
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/, "");
    const candidates = [cleaned];
    const objectStart = cleaned.indexOf("{");
    const objectEnd = cleaned.lastIndexOf("}");
    if (objectStart >= 0 && objectEnd > objectStart) {
      candidates.push(cleaned.slice(objectStart, objectEnd + 1));
    } else {
      const arrayStart = cleaned.indexOf("[");
      const arrayEnd = cleaned.lastIndexOf("]");
      if (arrayStart >= 0 && arrayEnd > arrayStart) {
        candidates.push(cleaned.slice(arrayStart, arrayEnd + 1));
      }
    }
    for (const candidate of [...new Set(candidates)]) {
      try {
        return JSON.parse(candidate);
      } catch {
        // Try the next bounded candidate before requesting one clean retry.
      }
    }
    const error = new Error(
      "The AI provider returned malformed or incomplete structured data.",
    );
    error.name = "ProviderJsonParseError";
    throw error;
  }

  function openAIResponseText(data) {
    if (data && typeof data.output_text === "string") return data.output_text;
    return (data?.output || [])
      .flatMap(item => item.content || [])
      .filter(item => item.type === "output_text")
      .map(item => item.text || "")
      .join("");
  }

  function truncate(value, maximum) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (text.length <= maximum) return text;
    return `${text.slice(0, maximum - 1).trim()}…`;
  }

  function knownEvidenceCitations(requestedIds, available, maximum = 8) {
    const byId = new Map(
      (Array.isArray(available) ? available : [])
        .filter(item => item && item.evidence_id)
        .map(item => [String(item.evidence_id), item]),
    );
    const limit = Number.isInteger(maximum) && maximum > 0
      ? Math.min(20, maximum)
      : 8;
    return [...new Set(
      (Array.isArray(requestedIds) ? requestedIds : []).map(String),
    )]
      .map(id => byId.get(id))
      .filter(Boolean)
      .slice(0, limit);
  }

  async function providerJson({
    provider,
    key,
    system,
    user,
    fetchImpl = globalThis.fetch,
    onRetry,
  }) {
    const cleanKey = String(key || "").trim();
    if (!cleanKey) {
      throw new Error(
        "Enter an API key to use AI refinement. Public catalog search does not require one.",
      );
    }
    if (typeof fetchImpl !== "function") {
      throw new Error("The browser does not provide a compatible fetch API.");
    }

    const requestText = async attempt => {
      const retryInstruction = attempt
        ? "\n\nYour previous response was malformed or incomplete JSON. Return the entire answer again as one smaller valid JSON value. Shorten strings and return fewer list items if necessary. Do not use Markdown fences or add commentary outside the JSON."
        : "";
      if (provider === "anthropic") {
        const response = await fetchImpl("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-api-key": cleanKey,
            "anthropic-version": "2023-06-01",
            "anthropic-dangerous-direct-browser-access": "true",
          },
          body: JSON.stringify({
            model: ANTHROPIC_MODEL,
            max_tokens: MAX_OUTPUT_TOKENS,
            system: `${system}${retryInstruction}`,
            messages: [{ role: "user", content: user }],
          }),
        });
        if (!response.ok) {
          const body = await response.text();
          throw new Error(
            `Anthropic request failed (${response.status}): ${truncate(body, 280)}`,
          );
        }
        const data = await response.json();
        return (data.content || []).map(block => block.text || "").join("");
      }

      const response = await fetchImpl("https://api.openai.com/v1/responses", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${cleanKey}`,
        },
        body: JSON.stringify({
          model: OPENAI_MODEL,
          instructions: `${system}${retryInstruction}`,
          input: user,
          reasoning: { effort: "low" },
          text: { verbosity: "low" },
          max_output_tokens: MAX_OUTPUT_TOKENS,
          store: false,
        }),
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(
          `OpenAI request failed (${response.status}): ${truncate(body, 280)}`,
        );
      }
      return openAIResponseText(await response.json());
    };

    for (let attempt = 0; attempt < MAX_JSON_ATTEMPTS; attempt += 1) {
      try {
        return extractJson(await requestText(attempt));
      } catch (error) {
        if (
          error?.name !== "ProviderJsonParseError"
          || attempt + 1 >= MAX_JSON_ATTEMPTS
        ) {
          if (error?.name === "ProviderJsonParseError") {
            throw new Error(
              "The AI provider returned malformed structured data twice. Try the refinement again; ordinary catalog search is unaffected.",
            );
          }
          throw error;
        }
        if (typeof onRetry === "function") onRetry();
      }
    }
    throw new Error("The AI provider did not return structured data.");
  }

  globalThis.FUNDING_AI = Object.freeze({
    ANTHROPIC_MODEL,
    OPENAI_MODEL,
    extractJson,
    knownEvidenceCitations,
    openAIResponseText,
    providerJson,
  });
})();
