// __VOCAB__
// __LLM__
// __PROMPTS_RECONSTRUCTION__
// Step 2 of the prompt chain: reconstruct the incident and predict the damage it would cause.
// The model sees only the story: no photos, invoice, map or weather. Those are checked elsewhere,
// so this prediction stays independent of the other evidence.
// Two prompts are inlined above (reconstruction-v2 for general models, reconstruction-ft1 for the
// fine-tuned model); "LLM settings" picks one.
// Outputs one item per call: 1 when the provider returns 3 answers at once, else 3.
const n = $('Normalize input').first().json;
const settings = $('LLM settings').first().json;
const provider = settings.providers.reconstruction;
const PROMPT = PROMPTS[settings.reconstruction_prompt];
if (!PROMPT) throw new Error(`Unknown reconstruction prompt ${settings.reconstruction_prompt}`);
const { facts } = $('Verify extracted facts').first().json;
const body = PROMPT.buildRequest({ description: n.description, facts });
// ft1 gives its schema separately (it is not sent to the model); the others send it.
const schema = PROMPT.schema || body.response_format.json_schema.schema;

return LLM.toRequests(body, provider, 'reconstruction').map((b) => ({
  json: {
    prompt_version: PROMPT.version,
    provider: provider.name,
    facts,
    parts_vocabulary: VOCAB.PARTS,
    url: provider.url,
    schema,
    body: b,
  },
}));
