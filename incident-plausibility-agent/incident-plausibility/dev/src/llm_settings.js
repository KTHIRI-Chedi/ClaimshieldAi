// __LLM__
// ===== Choose the AI provider for each step here =====
// groq (free key) | gemini (free key) | openrouter (free models) | ollama (local, no key) | openai (paid)
// The key goes in the Header Auth credential of both LLM nodes:  Name: Authorization   Value: Bearer <key>
// (Ollama ignores the key, so one credential works when the two steps use different providers.)
const PROVIDER = {
  extraction: 'groq',
  reconstruction: 'groq', // 'ollama' to use the fine-tuned model (see dev/finetune/README.md)
};

// Optional: other models than the defaults in dev/prompts/llm.js.
// Fine-tuned model: reconstruction: 'claimshield-recon' (the Ollama preset already uses it).
const MODEL_OVERRIDES = { extraction: null, reconstruction: null };

// Reconstruction prompt: 'v2' (few-shot, for general models) or 'ft1' (short prompt, for the
// fine-tuned model, which learned the format in training).
const RECONSTRUCTION_PROMPT = 'v2';

// Reconstruction answers to compare (self-consistency). 3 is the design; 1 is faster and uses a
// third of the tokens, for quick tests on a free tier or a slow CPU.
const RECONSTRUCTION_SAMPLES = 3;

// Seconds between LLM calls. null = the provider's default (Groq 25 s, Gemini 7 s, Ollama/OpenAI 0).
// If you still get "too many requests" (429), raise it; with a paid key, set 0.
const CALL_INTERVAL_SECONDS = null;

const names = typeof PROVIDER === 'string' ? { extraction: PROVIDER, reconstruction: PROVIDER } : PROVIDER;
const provider = (role) => {
  const preset = LLM.PROVIDERS[names[role]];
  if (!preset) throw new Error(`Unknown provider "${names[role]}" for ${role}. Use one of: ${Object.keys(LLM.PROVIDERS).join(', ')}`);
  return {
    name: names[role],
    ...preset,
    models: { ...preset.models, [role]: MODEL_OVERRIDES[role] || preset.models[role] },
    callIntervalMs: CALL_INTERVAL_SECONDS === null ? preset.callIntervalMs : CALL_INTERVAL_SECONDS * 1000,
    samples: Math.max(1, Math.min(5, RECONSTRUCTION_SAMPLES)),
  };
};
const providers = { extraction: provider('extraction'), reconstruction: provider('reconstruction') };
if (!['v2', 'ft1'].includes(RECONSTRUCTION_PROMPT)) throw new Error('RECONSTRUCTION_PROMPT must be "v2" or "ft1"');

return [{
  json: {
    providers,
    reconstruction_prompt: `reconstruction-${RECONSTRUCTION_PROMPT}`,
    // Pause between the extraction call and the reconstruction calls: only needed when both go to
    // the same rate-limited provider.
    pause_seconds: providers.extraction.name === providers.reconstruction.name
      ? providers.reconstruction.callIntervalMs / 1000 : 0,
  },
}];
