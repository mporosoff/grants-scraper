(() => {
  "use strict";

  const OPENAI_MODEL = "gpt-5.6-luna";
  const ANTHROPIC_MODEL = "claude-sonnet-5";
  const MAX_OUTPUT_TOKENS = 5000;
  const REQUEST_TIMEOUT_MS = 60_000;
  const MAX_ATTEMPTS = 2;

  const stringArray = (maximum, itemMaximum = 240, minimum = 0) => ({
    type: "array",
    items: { type: "string", maxLength: itemMaximum },
    ...(minimum ? { minItems: minimum } : {}),
    maxItems: maximum,
  });

  const STRUCTURED_OPERATIONS = Object.freeze({
    search_plan: Object.freeze({
      name: "funding_search_plan_v1",
      description: "A bounded terminology plan for searching the public funding catalog.",
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          interpretation: { type: "string", maxLength: 500 },
          search_terms: {
            ...stringArray(16, 120, 5),
            uniqueItems: true,
          },
          avoid_terms: stringArray(8, 120),
        },
        required: ["interpretation", "search_terms", "avoid_terms"],
      },
    }),
    refinement_shortlist: Object.freeze({
      name: "funding_refinement_shortlist_v1",
      description: "A bounded shortlist drawn only from supplied funding opportunities.",
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          summary: { type: "string", maxLength: 1200 },
          matches: {
            type: "array",
            maxItems: 12,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                id: { type: "string", maxLength: 180 },
                score: { type: "integer", minimum: 0, maximum: 100 },
                verdict: { type: "string", enum: ["Strong fit", "Possible fit", "Weak fit"] },
                reason: { type: "string", maxLength: 900 },
                concern: { type: "string", maxLength: 900 },
              },
              required: ["id", "score", "verdict", "reason", "concern"],
            },
          },
          follow_up_suggestions: stringArray(4, 300),
        },
        required: ["summary", "matches", "follow_up_suggestions"],
      },
    }),
    result_chat: Object.freeze({
      name: "funding_result_chat_v1",
      description: "An evidence-grounded answer about the supplied funding results.",
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          answer: { type: "string", maxLength: 10_000 },
          referenced_result_ids: stringArray(8, 180),
          citation_evidence_ids: stringArray(8, 180),
          result_action: { type: "string", enum: ["focus", "suggest_focus", "none"] },
          focus_result_ids: stringArray(20, 180),
        },
        required: [
          "answer",
          "referenced_result_ids",
          "citation_evidence_ids",
          "result_action",
          "focus_result_ids",
        ],
      },
    }),
    notice_chat: Object.freeze({
      name: "funding_notice_chat_v1",
      description: "An answer grounded only in a supplied public funding notice extract.",
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          answer: { type: "string", maxLength: 10_000 },
          page_references: {
            type: "array",
            maxItems: 12,
            items: { type: "integer", minimum: 1 },
          },
        },
        required: ["answer", "page_references"],
      },
    }),
    institution_question_translation: Object.freeze({
      name: "institution_question_translation_v1",
      description: "Visible public-award filters and a bounded answer intent for one institution question.",
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          agency: { type: "string", enum: ["all", "NSF", "NIH", "DOE"] },
          program: { type: "string", maxLength: 160 },
          topic: { type: "string", maxLength: 500 },
          pi: { type: "string", maxLength: 160 },
          program_officer: { type: "string", maxLength: 160 },
          year_start: { type: "string", maxLength: 4 },
          year_end: { type: "string", maxLength: 4 },
          answer_intent: {
            type: "string",
            enum: ["count", "investigators", "programs", "years", "awards", "narrative"],
          },
          narrative_needed: { type: "boolean" },
        },
        required: [
          "agency",
          "program",
          "topic",
          "pi",
          "program_officer",
          "year_start",
          "year_end",
          "answer_intent",
          "narrative_needed",
        ],
      },
    }),
    institution_narrative: Object.freeze({
      name: "institution_narrative_synthesis_v1",
      description: "Evidence-cited narrative claims grounded in supplied public award fields.",
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          claims: {
            type: "array",
            maxItems: 6,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                text: { type: "string", maxLength: 700 },
                evidence_ids: stringArray(8, 120),
              },
              required: ["text", "evidence_ids"],
            },
          },
        },
        required: ["claims"],
      },
    }),
  });

  const ERROR_MESSAGES = Object.freeze({
    authentication: "The provider rejected this API key. Check or replace the key, then try again.",
    authorization_model: "This provider account cannot use the selected model. Check model access, then try again.",
    quota_rate: "The provider reported a quota or rate limit. Check provider usage and billing, then try again.",
    unsupported_contract: "The selected provider or model does not support the required structured-response contract.",
    network_cors: "The browser could not reach the AI provider. Check the network and provider browser-access settings, then try again.",
    timeout: "The AI provider request timed out. Your search and entered information were preserved; try again.",
    incomplete: "The AI provider could not complete a valid structured response after one bounded retry.",
    refusal: "The AI provider declined this request. Ordinary catalog search and deterministic award summaries remain available.",
    schema_validation: "The AI provider response did not match the required structure after one bounded retry.",
    malformed: "The AI provider returned malformed structured data after one bounded retry.",
    provider_unavailable: "The AI provider is temporarily unavailable. Your search and entered information were preserved; try again later.",
  });

  class ProviderStructuredError extends Error {
    constructor(category, { retryable = false } = {}) {
      super(ERROR_MESSAGES[category] || "The AI provider request could not be completed.");
      this.name = "ProviderStructuredError";
      this.category = category;
      this.code = `provider_${category}`;
      this.retryable = retryable;
    }
  }

  function plainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function valueMatchesType(value, type) {
    if (type === "null") return value === null;
    if (type === "array") return Array.isArray(value);
    if (type === "object") return plainObject(value);
    if (type === "integer") return Number.isInteger(value);
    if (type === "number") return typeof value === "number" && Number.isFinite(value);
    return typeof value === type;
  }

  function schemaProblem(value, schema, path = "$") {
    const types = Array.isArray(schema?.type) ? schema.type : [schema?.type];
    if (types[0] && !types.some(type => valueMatchesType(value, type))) {
      return `${path}:type`;
    }
    if (Array.isArray(schema?.enum) && !schema.enum.some(item => Object.is(item, value))) {
      return `${path}:enum`;
    }
    if (typeof value === "string") {
      if (Number.isInteger(schema.minLength) && value.length < schema.minLength) return `${path}:minLength`;
      if (Number.isInteger(schema.maxLength) && value.length > schema.maxLength) return `${path}:maxLength`;
    }
    if (typeof value === "number") {
      if (Number.isFinite(schema.minimum) && value < schema.minimum) return `${path}:minimum`;
      if (Number.isFinite(schema.maximum) && value > schema.maximum) return `${path}:maximum`;
    }
    if (Array.isArray(value)) {
      if (Number.isInteger(schema.minItems) && value.length < schema.minItems) return `${path}:minItems`;
      if (Number.isInteger(schema.maxItems) && value.length > schema.maxItems) return `${path}:maxItems`;
      for (let index = 0; index < value.length; index += 1) {
        const problem = schemaProblem(value[index], schema.items || {}, `${path}[${index}]`);
        if (problem) return problem;
      }
    }
    if (plainObject(value)) {
      const properties = schema.properties || {};
      for (const key of schema.required || []) {
        if (!Object.prototype.hasOwnProperty.call(value, key)) return `${path}.${key}:required`;
      }
      if (schema.additionalProperties === false) {
        const unknown = Object.keys(value).find(key => !Object.prototype.hasOwnProperty.call(properties, key));
        if (unknown) return `${path}.${unknown}:additionalProperty`;
      }
      for (const [key, propertySchema] of Object.entries(properties)) {
        if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
        const problem = schemaProblem(value[key], propertySchema, `${path}.${key}`);
        if (problem) return problem;
      }
    }
    return "";
  }

  function validateStructuredValue(value, schema) {
    if (schemaProblem(value, schema)) {
      throw new ProviderStructuredError("schema_validation", { retryable: true });
    }
    return value;
  }

  const ANTHROPIC_UNSUPPORTED_SCHEMA_CONSTRAINTS = Object.freeze({
    minimum: value => `Must be greater than or equal to ${value}.`,
    maximum: value => `Must be less than or equal to ${value}.`,
    exclusiveMinimum: value => `Must be greater than ${value}.`,
    exclusiveMaximum: value => `Must be less than ${value}.`,
    multipleOf: value => `Must be a multiple of ${value}.`,
    minLength: value => `Must contain at least ${value} characters.`,
    maxLength: value => `Must contain no more than ${value} characters.`,
    pattern: value => `Must match the pattern ${value}.`,
    format: value => `Must use the ${value} format.`,
    minItems: value => `Must contain at least ${value} items.`,
    maxItems: value => `Must contain no more than ${value} items.`,
    uniqueItems: value => value ? "Items must be unique." : "",
    minProperties: value => `Must contain at least ${value} properties.`,
    maxProperties: value => `Must contain no more than ${value} properties.`,
  });

  function schemaForProvider(schema, provider) {
    if (Array.isArray(schema)) return schema.map(value => schemaForProvider(value, provider));
    if (!plainObject(schema)) return schema;
    const result = {};
    const notes = [];
    for (const [key, value] of Object.entries(schema)) {
      const explain = provider === "anthropic" && ANTHROPIC_UNSUPPORTED_SCHEMA_CONSTRAINTS[key];
      if (explain) {
        const note = explain(value);
        if (note) notes.push(note);
        continue;
      }
      result[key] = schemaForProvider(value, provider);
    }
    if (notes.length) {
      result.description = [String(result.description || "").trim(), ...notes]
        .filter(Boolean)
        .join(" ");
    }
    return result;
  }

  function extractJson(text) {
    try {
      return JSON.parse(String(text || ""));
    } catch {
      throw new ProviderStructuredError("malformed", { retryable: true });
    }
  }

  function classifyProviderEnvelope(value, status = 0) {
    const code = String(value?.error?.code || value?.error?.type || value?.code || value?.type || "").toLowerCase();
    if (status === 401 || /authentication|invalid_api_key/.test(code)) return "authentication";
    if (status === 403 || status === 404 || /permission|model_not_found|not_found/.test(code)) return "authorization_model";
    if (status === 429 || /rate_limit|quota|billing/.test(code)) return "quota_rate";
    if (status === 408 || /timeout/.test(code)) return "timeout";
    if (status === 400 || /invalid_request|unsupported|schema/.test(code)) return "unsupported_contract";
    return "provider_unavailable";
  }

  function providerFailure(envelope, status) {
    throw new ProviderStructuredError(classifyProviderEnvelope(envelope, status));
  }

  async function fetchJsonBounded(fetchImpl, url, options, timeoutMs) {
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller && typeof setTimeout === "function"
      ? setTimeout(() => controller.abort(), timeoutMs)
      : null;
    try {
      const response = await fetchImpl(url, {
        ...options,
        ...(controller ? { signal: controller.signal } : {}),
      });
      try {
        return { response, data: await response.json(), malformed: false };
      } catch (error) {
        if (error?.name === "AbortError") throw new ProviderStructuredError("timeout");
        if (error?.name !== "SyntaxError") throw new ProviderStructuredError("network_cors");
        return { response, data: null, malformed: true };
      }
    } catch (error) {
      if (error instanceof ProviderStructuredError) throw error;
      if (error?.name === "AbortError") throw new ProviderStructuredError("timeout");
      throw new ProviderStructuredError("network_cors");
    } finally {
      if (timer !== null && typeof clearTimeout === "function") clearTimeout(timer);
    }
  }

  function openAIResponseText(data) {
    if (!plainObject(data)) throw new ProviderStructuredError("malformed", { retryable: true });
    if (data.error) throw new ProviderStructuredError(classifyProviderEnvelope(data));
    if (data.status === "incomplete" || data.incomplete_details) {
      throw new ProviderStructuredError("incomplete", { retryable: true });
    }
    if (data.status !== "completed") throw new ProviderStructuredError("provider_unavailable");
    const messages = (Array.isArray(data.output) ? data.output : []).filter(item => item?.type === "message");
    if (messages.length !== 1) throw new ProviderStructuredError("malformed", { retryable: true });
    const message = messages[0];
    if (message.status === "incomplete") throw new ProviderStructuredError("incomplete", { retryable: true });
    if (message.status !== "completed" || message.role !== "assistant" || !Array.isArray(message.content)) {
      throw new ProviderStructuredError("malformed", { retryable: true });
    }
    if (message.content.some(item => item?.type === "refusal")) {
      throw new ProviderStructuredError("refusal");
    }
    const textBlocks = message.content.filter(item => item?.type === "output_text");
    if (textBlocks.length !== 1 || typeof textBlocks[0].text !== "string" || !textBlocks[0].text) {
      throw new ProviderStructuredError("malformed", { retryable: true });
    }
    return textBlocks[0].text;
  }

  function anthropicResponseText(data) {
    if (!plainObject(data)) throw new ProviderStructuredError("malformed", { retryable: true });
    if (data.error || data.type === "error") {
      throw new ProviderStructuredError(classifyProviderEnvelope(data));
    }
    if (["max_tokens", "model_context_window_exceeded"].includes(data.stop_reason)) {
      throw new ProviderStructuredError("incomplete", { retryable: true });
    }
    if (data.stop_reason === "refusal") throw new ProviderStructuredError("refusal");
    if (data.stop_reason !== "end_turn" || !Array.isArray(data.content)) {
      throw new ProviderStructuredError("malformed", { retryable: true });
    }
    const unsupported = data.content.find(block => !["text", "thinking", "redacted_thinking"].includes(block?.type));
    if (unsupported) throw new ProviderStructuredError("malformed", { retryable: true });
    const textBlocks = data.content.filter(block => block?.type === "text");
    if (textBlocks.length !== 1 || typeof textBlocks[0].text !== "string" || !textBlocks[0].text) {
      throw new ProviderStructuredError("malformed", { retryable: true });
    }
    return textBlocks[0].text;
  }

  async function requestStructured({ provider, key, system, user, operation, attempt, fetchImpl, timeoutMs }) {
    const contract = STRUCTURED_OPERATIONS[operation];
    if (!contract) throw new ProviderStructuredError("unsupported_contract");
    const retryInstruction = attempt
      ? "\n\nReturn a smaller complete response that still matches the supplied schema. Shorten prose and include fewer optional list items."
      : "";
    if (provider === "anthropic") {
      const { response, data, malformed } = await fetchJsonBounded(
        fetchImpl,
        "https://api.anthropic.com/v1/messages",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "anthropic-dangerous-direct-browser-access": "true",
          },
          body: JSON.stringify({
            model: ANTHROPIC_MODEL,
            max_tokens: MAX_OUTPUT_TOKENS,
            system: `${system}${retryInstruction}`,
            messages: [{ role: "user", content: user }],
            output_config: {
              format: {
                type: "json_schema",
                schema: schemaForProvider(contract.schema, "anthropic"),
              },
            },
          }),
        },
        timeoutMs,
      );
      if (!response.ok) providerFailure(data, response.status);
      if (malformed) throw new ProviderStructuredError("malformed", { retryable: true });
      return anthropicResponseText(data);
    }
    if (provider !== "openai") throw new ProviderStructuredError("unsupported_contract");
    const { response, data, malformed } = await fetchJsonBounded(
      fetchImpl,
      "https://api.openai.com/v1/responses",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${key}`,
        },
        body: JSON.stringify({
          model: OPENAI_MODEL,
          instructions: `${system}${retryInstruction}`,
          input: user,
          reasoning: { effort: "low" },
          text: {
            verbosity: "low",
            format: {
              type: "json_schema",
              name: contract.name,
              description: contract.description,
              schema: contract.schema,
              strict: true,
            },
          },
          max_output_tokens: MAX_OUTPUT_TOKENS,
          store: false,
        }),
      },
      timeoutMs,
    );
    if (!response.ok) providerFailure(data, response.status);
    if (malformed) throw new ProviderStructuredError("malformed", { retryable: true });
    return openAIResponseText(data);
  }

  async function structuredResult({
    provider,
    key,
    system,
    user,
    operation,
    fetchImpl = globalThis.fetch,
    onRetry,
    timeoutMs = REQUEST_TIMEOUT_MS,
  }) {
    const cleanKey = String(key || "").trim();
    if (!cleanKey) {
      throw new Error(
        "Enter an API key to use AI refinement. Public catalog search does not require one.",
      );
    }
    if (typeof fetchImpl !== "function") throw new ProviderStructuredError("network_cors");
    if (!STRUCTURED_OPERATIONS[operation]) throw new ProviderStructuredError("unsupported_contract");

    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      try {
        const text = await requestStructured({
          provider,
          key: cleanKey,
          system,
          user,
          operation,
          attempt,
          fetchImpl,
          timeoutMs: Math.max(1_000, Math.min(60_000, Number(timeoutMs) || REQUEST_TIMEOUT_MS)),
        });
        return validateStructuredValue(extractJson(text), STRUCTURED_OPERATIONS[operation].schema);
      } catch (error) {
        if (!(error instanceof ProviderStructuredError)) throw error;
        if (!error.retryable || attempt + 1 >= MAX_ATTEMPTS) throw error;
        if (typeof onRetry === "function") onRetry({ category: error.category });
      }
    }
    throw new ProviderStructuredError("malformed");
  }

  function knownEvidenceCitations(requestedIds, available, maximum = 8) {
    const byId = new Map(
      (Array.isArray(available) ? available : [])
        .filter(item => item && item.evidence_id)
        .map(item => [String(item.evidence_id), item]),
    );
    const limit = Number.isInteger(maximum) && maximum > 0 ? Math.min(20, maximum) : 8;
    return [...new Set((Array.isArray(requestedIds) ? requestedIds : []).map(String))]
      .map(id => byId.get(id))
      .filter(Boolean)
      .slice(0, limit);
  }

  globalThis.FUNDING_AI = Object.freeze({
    ANTHROPIC_MODEL,
    OPENAI_MODEL,
    ProviderStructuredError,
    STRUCTURED_OPERATIONS,
    anthropicResponseText,
    extractJson,
    knownEvidenceCitations,
    openAIResponseText,
    schemaForProvider,
    structuredResult,
    validateStructuredValue,
  });
})();
