// LLM provider layer. The prompts are written once (OpenAI chat format); this turns them
// into requests any OpenAI-compatible provider accepts, and checks the answers.
// Pick the provider in the "LLM settings" node of the workflow.
const LLM = (() => {
  // Free model names and limits change: check your provider's console if a call fails.
  // structured: 'json_schema' = strict schema enforced by the provider
  //             'json_object' = JSON mode; the schema goes into the prompt
  //             'prompt'      = no JSON mode; the schema goes into the prompt
  // supportsN: provider can return several answers in one call (n = 3)
  // callIntervalMs: pause between LLM calls. Free tiers limit tokens per minute; one claim uses
  //   about 10,000 tokens (1 extraction + 3 reconstruction calls), so calls must be spread out.
  // extra: request fields added when the model name contains the key.
  const PROVIDERS = {
    groq: {
      url: 'https://api.groq.com/openai/v1/chat/completions',
      // openai/gpt-oss-120b: confirmed available on Groq's free tier during setup.
      models: { extraction: 'openai/gpt-oss-120b', reconstruction: 'openai/gpt-oss-120b' },
      structured: 'json_object', supportsN: false, keyHint: 'console.groq.com → API Keys (free)',
      callIntervalMs: 25000,
      // gpt-oss "thinks" before answering; low effort keeps it fast and within the token limit.
      extra: { 'gpt-oss': { reasoning_effort: 'low' } },
    },
    gemini: {
      url: 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
      models: { extraction: 'gemini-2.5-flash-lite', reconstruction: 'gemini-2.5-flash' },
      structured: 'prompt', supportsN: false, keyHint: 'aistudio.google.com → Get API key (free)',
      callIntervalMs: 7000,
    },
    openrouter: {
      url: 'https://openrouter.ai/api/v1/chat/completions',
      models: { extraction: 'meta-llama/llama-3.3-70b-instruct:free', reconstruction: 'meta-llama/llama-3.3-70b-instruct:free' },
      structured: 'prompt', supportsN: false, keyHint: 'openrouter.ai → Keys (free models end in :free)',
      callIntervalMs: 4000,
    },
    ollama: {
      // Runs on your own computer: no key, no cost. From inside Docker, the host is host.docker.internal.
      url: 'http://host.docker.internal:11434/v1/chat/completions',
      // claimshield-recon = the fine-tuned Qwen2.5-3B (dev/finetune). qwen2.5:3b = the same model
      // before fine-tuning, for comparisons (ollama pull qwen2.5:3b).
      models: { extraction: 'qwen2.5:3b', reconstruction: 'claimshield-recon' },
      structured: 'json_object', supportsN: false, keyHint: 'no key needed (any value works)',
      callIntervalMs: 0,
    },
    openai: {
      url: 'https://api.openai.com/v1/chat/completions',
      models: { extraction: 'gpt-4o-mini', reconstruction: 'gpt-4o' },
      structured: 'json_schema', supportsN: true, keyHint: 'platform.openai.com (paid)',
      callIntervalMs: 0,
    },
  };

  const schemaInstruction = (schema) =>
    '\n\nOUTPUT FORMAT: reply with ONE JSON object and nothing else (no prose, no code fences). '
    + 'It must match this JSON schema exactly; every key is required, and enum fields must use one of the listed values:\n'
    + JSON.stringify(schema);

  // OpenAI-style request body -> list of request bodies for the chosen provider.
  // Self-consistency (n = 3) becomes 3 separate calls when the provider has no "n".
  // provider.samples (set in "LLM settings") can lower the number of reconstruction samples.
  const toRequests = (body, provider, role) => {
    const b = JSON.parse(JSON.stringify(body));
    b.model = provider.models[role];
    b.stream = false; // one complete answer, not a stream of chunks
    for (const [match, fields] of Object.entries(provider.extra || {})) {
      if (b.model.includes(match)) Object.assign(b, fields);
    }
    const samples = b.n > 1 && provider.samples ? provider.samples : b.n || 1;
    delete b.n;
    const rf = b.response_format;
    if (rf && rf.type === 'json_schema' && provider.structured !== 'json_schema') {
      b.messages[0].content += schemaInstruction(rf.json_schema.schema);
      if (provider.structured === 'json_object') b.response_format = { type: 'json_object' };
      else delete b.response_format;
    }
    if (samples > 1 && provider.supportsN) return [{ ...b, n: samples }];
    return Array.from({ length: samples }, () => b);
  };

  // Text of the first answer in a chat-completions response. When the LLM node passed on
  // something else (a provider error, a text response), say what it was instead of crashing.
  const contentOf = (json) => {
    let j = json || {};
    // Streamed answer ("stream": true): text lines "data: {chunk}". Join the chunks' content.
    if (!j.choices && typeof j.data === 'string' && j.data.trimStart().startsWith('data:')) {
      const text = j.data.split('\n')
        .map((line) => line.trim())
        .filter((line) => line.startsWith('data:') && !line.includes('[DONE]'))
        .map((line) => { try { return JSON.parse(line.slice(5)); } catch (e) { return null; } })
        .filter(Boolean)
        .map((chunk) => (chunk.choices && chunk.choices[0] && chunk.choices[0].delta && chunk.choices[0].delta.content) || '')
        .join('');
      j = { choices: [{ message: { content: text } }] };
    }
    // HTTP node set to return text: the JSON arrives as a string in "data".
    if (!j.choices && typeof j.data === 'string') { try { j = JSON.parse(j.data); } catch (e) { /* below */ } }
    const content = j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content;
    if (typeof content === 'string') return content;
    const err = j.error && (j.error.message || j.error.description || j.error);
    const hint = err
      ? `The provider returned an error: ${typeof err === 'string' ? err : JSON.stringify(err)}`
      : `Unexpected response: ${JSON.stringify(j).slice(0, 300)}`;
    throw new Error(`${hint}. Check the LLM node's credential (Header Auth, value "Bearer <key>"), URL and model. `
      + 'In the LLM node, Settings → On Error must be "Stop Workflow" and Response Format "JSON".');
  };

  // Tolerates code fences or text around the JSON, which some free models add.
  const parse = (content) => {
    const text = String(content || '').replace(/```(?:json)?/gi, '');
    const start = text.indexOf('{');
    const end = text.lastIndexOf('}');
    if (start < 0 || end <= start) {
      throw new Error(`The model answered with text instead of JSON: "${text.trim().slice(0, 160)}". `
        + 'This usually means the LLM node did not send the request built by the previous node. '
        + 'In the LLM node, the body must be JSON with the expression {{ JSON.stringify($json.body) }} '
        + 'and the URL {{ $json.url }}. Re-importing the workflow restores both.');
    }
    return JSON.parse(text.slice(start, end + 1));
  };

  // Makes an answer match the schema when the provider does not enforce it: missing keys get
  // an empty value, values outside an enum become "unknown"/null, wrong types are fixed.
  const conform = (value, schema) => {
    const types = [].concat(schema.type || []);
    const nullable = types.includes('null');
    if (schema.enum) {
      // Fall back to the value that claims the least: unknown, empty, or low confidence.
      if (schema.enum.includes(value)) return value;
      if (schema.enum.includes('unknown')) return 'unknown';
      if (nullable) return null;
      if (schema.enum.includes('low')) return 'low';
      return schema.enum[0];
    }
    if (types.includes('object')) {
      const src = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
      const out = {};
      for (const [k, sub] of Object.entries(schema.properties || {})) out[k] = conform(src[k], sub);
      return out;
    }
    if (types.includes('array')) {
      const arr = Array.isArray(value) ? value : [];
      const item = schema.items || {};
      // Drop list entries that are invalid instead of guessing a value for them
      // (an invalid road feature must not turn into "roundabout").
      const enumsOk = (v) => Object.entries(item.properties || {})
        .every(([k, s]) => !s.enum || s.enum.includes(v[k]));
      return arr
        .filter((v) => !item.enum || item.enum.includes(v))
        .filter((v) => !(item.type === 'object' && (!v || typeof v !== 'object' || !enumsOk(v))))
        .map((v) => conform(v, item));
    }
    if (types.includes('integer')) {
      const num = Math.round(Number(value));
      if (value !== null && value !== undefined && value !== '' && Number.isFinite(num)) return num;
      return nullable ? null : 0;
    }
    if (types.includes('boolean')) return value === true || value === 'true';
    if (types.includes('string')) {
      if (typeof value === 'string') return value;
      if (value === null || value === undefined) return nullable ? null : '';
      return String(value);
    }
    return value ?? null;
  };

  return { PROVIDERS, toRequests, contentOf, parse, conform };
})();
