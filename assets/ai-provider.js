(() => {
  "use strict";

  const OPENAI_MODEL = "gpt-5.6-luna";
  const ANTHROPIC_MODEL = "claude-sonnet-5";

  function extractJson(text) {
    const cleaned = String(text || "")
      .trim()
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/, "");
    try {
      return JSON.parse(cleaned);
    } catch {
      const objectStart = cleaned.indexOf("{");
      const objectEnd = cleaned.lastIndexOf("}");
      if (objectStart >= 0 && objectEnd > objectStart) {
        return JSON.parse(cleaned.slice(objectStart, objectEnd + 1));
      }
      const arrayStart = cleaned.indexOf("[");
      const arrayEnd = cleaned.lastIndexOf("]");
      if (arrayStart >= 0 && arrayEnd > arrayStart) {
        return JSON.parse(cleaned.slice(arrayStart, arrayEnd + 1));
      }
      throw new Error(
        "The AI provider returned an answer that was not valid JSON.",
      );
    }
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

  async function providerJson({
    provider,
    key,
    system,
    user,
    fetchImpl = globalThis.fetch,
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
          max_tokens: 3000,
          system,
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
      return extractJson(
        (data.content || []).map(block => block.text || "").join(""),
      );
    }

    const response = await fetchImpl("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${cleanKey}`,
      },
      body: JSON.stringify({
        model: OPENAI_MODEL,
        instructions: system,
        input: user,
        reasoning: { effort: "low" },
        text: { verbosity: "low" },
        max_output_tokens: 3000,
        store: false,
      }),
    });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(
        `OpenAI request failed (${response.status}): ${truncate(body, 280)}`,
      );
    }
    return extractJson(openAIResponseText(await response.json()));
  }

  globalThis.FUNDING_AI = Object.freeze({
    ANTHROPIC_MODEL,
    OPENAI_MODEL,
    extractJson,
    openAIResponseText,
    providerJson,
  });
})();
