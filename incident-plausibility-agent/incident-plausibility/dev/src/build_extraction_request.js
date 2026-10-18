// __VOCAB__
// __LLM__
// __PROMPT_EXTRACTION__
// Step 1 of the prompt chain: structured facts from the free-text description.
// The prompt itself is inlined above from dev/prompts/ (see ACTIVE in dev/build.py).
const n = $('Normalize input').first().json;
const provider = $('LLM settings').first().json.providers.extraction;
const body = PROMPT.buildRequest({ description: n.description });
const schema = body.response_format.json_schema.schema;

return LLM.toRequests(body, provider, 'extraction').map((b) => ({
  json: { prompt_version: PROMPT.version, provider: provider.name, url: provider.url, schema, body: b },
}));
