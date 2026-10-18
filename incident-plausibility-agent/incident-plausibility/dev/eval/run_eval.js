// Prompt evaluation: runs the labeled claims in claims.json through several configurations
// (default: BEFORE = extraction-v2 + reconstruction-v1, AFTER = extraction-v3 + reconstruction-v2)
// with real LLMs, applies the same code guardrails as the workflow, and writes a comparison
// report to results/.
//
// Usage (PowerShell):   $env:LLM_API_KEY="gsk_..."; node dev/eval/run_eval.js --provider groq
// Usage (bash):         LLM_API_KEY=gsk_... node dev/eval/run_eval.js --provider groq
// Options:  --provider groq|gemini|openrouter|ollama|openai   default provider for both steps
//           --ext-provider groq   provider for the extraction step only
//           --delay 25000        milliseconds between calls (default: each provider's interval in llm.js)
//           --only c04,c12       run some claims only
//           --configs v2+v1,v3+v2   extraction+reconstruction prompt versions to compare. A config can
//                                name the reconstruction provider and model:  v3+ft1@ollama:claimshield-recon
//           --mock               no API calls: checks the runner itself with fake answers
//
// Fine-tuning comparison (extraction on Groq, computed once per claim and reused):
//   node dev/eval/run_eval.js --ext-provider groq --configs "v3+ft1@ollama:qwen2.5:3b,v3+v2@ollama:qwen2.5:3b,v3+ft1@ollama:claimshield-recon,v3+v2@groq"
const fs = require('fs');
const path = require('path');

const DEV = path.join(__dirname, '..');
const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; };
const MOCK = args.includes('--mock');
const ONLY = opt('--only') ? opt('--only').split(',') : null;
const DEFAULT_PROVIDER = opt('--provider') || 'groq';
const EXT_PROVIDER = opt('--ext-provider') || DEFAULT_PROVIDER;
const CONFIGS = (opt('--configs') || 'v2+v1,v3+v2').split(',').map((c) => c.trim()).filter(Boolean).map((c) => {
  const [versions, target] = c.split('@');
  const [e, r] = versions.split('+');
  const [recProvider, ...model] = (target || DEFAULT_PROVIDER).split(':');
  return {
    extraction: `extraction.${e}.js`,
    reconstruction: `reconstruction.${r}.js`,
    recProvider,
    recModel: model.length ? model.join(':') : null, // model names can contain ':' (qwen2.5:3b)
  };
});

const read = (f) => fs.readFileSync(path.join(DEV, 'prompts', f), 'utf8');
const load = (file) => new Function(`${read('vocabulary.js')}\n${read(file)}\nreturn PROMPT;`)();
const GROUNDING = new Function(`${read('grounding.js')}\nreturn GROUNDING;`)();
const LLM = new Function(`${read('llm.js')}\nreturn LLM;`)();
const { claims } = JSON.parse(fs.readFileSync(path.join(__dirname, 'claims.json'), 'utf8'));

// A provider preset (dev/prompts/llm.js) with an optional model override for one step.
const providerFor = (name, role, model) => {
  const preset = LLM.PROVIDERS[name];
  if (!preset) { console.error(`Unknown provider ${name}`); process.exit(1); }
  return { name, ...preset, models: { ...preset.models, ...(model ? { [role]: model } : {}) } };
};
const KEY = process.env.LLM_API_KEY || process.env.OPENAI_API_KEY || '';
const usedProviders = new Set([EXT_PROVIDER, ...CONFIGS.map((c) => c.recProvider)]);
if (!MOCK && !KEY && [...usedProviders].some((n) => n !== 'ollama')) {
  const n = [...usedProviders].find((x) => x !== 'ollama');
  console.error(`Set LLM_API_KEY first. Get a ${n} key at: ${LLM.PROVIDERS[n] ? LLM.PROVIDERS[n].keyHint : '?'}`);
  console.error('(or use --mock to test the runner without API calls)');
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function callLLM(provider, body) {
  const url = provider.url.replace('host.docker.internal', 'localhost'); // outside Docker
  const delay = Number(opt('--delay') ?? provider.callIntervalMs);
  for (let attempt = 1; ; attempt += 1) {
    if (delay) await sleep(delay);
    const r = await fetch(url, {
      method: 'POST',
      headers: { Authorization: `Bearer ${provider.name === 'ollama' ? 'ollama' : KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (r.ok) return r.json();
    if (attempt >= 6 || ![429, 500, 502, 503].includes(r.status)) {
      throw new Error(`${provider.name} HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
    }
    // Rate limited: wait as long as the provider asks, or back off.
    const wait = Number(r.headers.get('retry-after')) * 1000 || 5000 * attempt;
    console.log(`    (${r.status}, waiting ${Math.round(wait / 1000)} s)`);
    await sleep(wait);
  }
}

// --mock: answers built from the labels, only to check the runner's plumbing.
function mockAnswer(kind, claim, prompt) {
  const L = claim.labels;
  const first = (k, dflt = null) => (L[k] ? L[k][0] : dflt);
  if (kind === 'extraction') {
    const grounded = prompt.version === 'extraction-v3';
    const q = grounded ? claim.description.slice(0, 25) : undefined;
    const f = {
      vehicle_state: first('vehicle_state', 'unknown'), maneuver: null, other_party: 'unknown',
      collision_direction: first('collision_direction', 'unknown'),
      stated_speed_kmh: L.speed ? L.speed[0] : null, stated_weather: first('weather'),
      stated_light: first('light'), summary: 'mock', manipulation_attempt: !!L.manipulation,
      manipulation_quote: L.manipulation ? claim.description.slice(0, 25) : null,
      stated_road_features: (L.road_features ? L.road_features[0] : []).map((x) => (grounded ? { feature: x, quote: q } : x)),
    };
    if (grounded) {
      for (const k of ['vehicle_state', 'collision_direction', 'stated_weather', 'stated_light']) f[`${k}_quote`] = q;
      f.stated_speed_quote = q;
    }
    return { choices: [{ message: { content: JSON.stringify(f) } }], usage: { total_tokens: 0 } };
  }
  const zone = L.zone ? L.zone[0] : 'unknown';
  // Two different parts of the text: two sentences, or the two halves of a single sentence.
  let parts = claim.description.split(/(?<=[.!?])\s+/);
  if (parts.length < 2) {
    const words = claim.description.split(' ');
    parts = [words.slice(0, words.length / 2).join(' '), words.slice(words.length / 2).join(' ')];
  }
  const contra = L.contradiction
    ? [prompt.version === 'reconstruction-v1' ? 'mock contradiction'
      : { quote_a: parts[0], quote_b: parts[1], explanation: 'mock' }]
    : [];
  const s = {
    reasoning: 'mock', scenario_type: 'other', impact_zone: zone, expected_parts: [],
    expected_severity_min: 1, expected_severity_max: 3, internal_contradictions: contra,
    confidence: L.abstain ? 'low' : 'high',
  };
  return { choices: [0, 1, 2].map(() => ({ message: { content: JSON.stringify(s) } })), usage: { total_tokens: 0 } };
}

const FACT_FIELDS = [
  ['vehicle_state', 'vehicle_state'], ['collision_direction', 'collision_direction'],
  ['weather', 'stated_weather'], ['light', 'stated_light'], ['speed', 'stated_speed_kmh'],
  ['road_features', 'stated_road_features'], ['manipulation', 'manipulation_attempt'],
];
const isEmpty = (v) => v === null || v === undefined || v === 'unknown' || v === false
  || (Array.isArray(v) && v.length === 0);

// Is one extracted value acceptable for its label? Unlabeled fields must be empty.
function checkField(labelKey, value, L) {
  const label = L[labelKey];
  if (label === undefined) return { ok: isEmpty(value), hallucinated: !isEmpty(value) };
  if (labelKey === 'speed') return { ok: Number.isFinite(value) && value >= label[0] && value <= label[1], hallucinated: false };
  if (labelKey === 'road_features') {
    const got = [...(value || [])].sort().join(',');
    return { ok: label.some((set) => [...set].sort().join(',') === got), hallucinated: false };
  }
  if (labelKey === 'manipulation') return { ok: !!value === label, hallucinated: !label && !!value };
  const ok = label.includes(value) || (label.includes(null) && isEmpty(value));
  return { ok, hallucinated: !ok && !isEmpty(value) && label.every((x) => x === null || x === 'unknown') };
}

const EXTRACTION_CACHE = new Map();
async function runConfig(config) {
  const EXT = load(config.extraction);
  const REC = load(config.reconstruction);
  const EXT_P = providerFor(EXT_PROVIDER, 'extraction', null);
  const REC_P = providerFor(config.recProvider, 'reconstruction', config.recModel);
  const name = `${EXT.version} + ${REC.version} @ ${REC_P.name}:${REC_P.models.reconstruction}`;
  const rows = [];
  let tokens = 0;
  let recSeconds = 0;
  for (const claim of claims.filter((c) => !ONLY || ONLY.some((o) => c.id.startsWith(o)))) {
    process.stdout.write(`  ${name}: ${claim.id}... `);
    const L = claim.labels;
    const extBody = EXT.buildRequest({ description: claim.description });
    const extSchema = extBody.response_format.json_schema.schema;
    // The extraction is the same for configs that share its prompt: compute it once per claim.
    const cacheKey = `${EXT.version}|${EXT_P.name}|${claim.id}`;
    const cached = EXTRACTION_CACHE.get(cacheKey);
    const extRes = cached || (MOCK ? mockAnswer('extraction', claim, EXT) : await callLLM(EXT_P, LLM.toRequests(extBody, EXT_P, 'extraction')[0]));
    if (!cached) { EXTRACTION_CACHE.set(cacheKey, extRes); tokens += extRes.usage ? extRes.usage.total_tokens : 0; }
    let raw;
    try { raw = LLM.conform(LLM.parse(LLM.contentOf(extRes)), extSchema); } catch (e) {
      console.log(`unreadable extraction (${e.message})`);
      raw = LLM.conform({}, extSchema);
    }
    const { facts, dropped } = GROUNDING.verifyFacts(raw, claim.description);

    const recBody = REC.buildRequest({ description: claim.description, facts });
    const recSchema = REC.schema || recBody.response_format.json_schema.schema;
    // Same as the workflow: 1 call with n = 3 (OpenAI) or 3 separate calls (free providers).
    const responses = MOCK ? [mockAnswer('reconstruction', claim, REC)] : [];
    const t0 = Date.now();
    if (!MOCK) for (const b of LLM.toRequests(recBody, REC_P, 'reconstruction')) responses.push(await callLLM(REC_P, b));
    recSeconds += (Date.now() - t0) / 1000 - (MOCK ? 0 : Number(opt('--delay') ?? REC_P.callIntervalMs) / 1000 * responses.length);
    tokens += responses.reduce((t, r) => t + (r.usage ? r.usage.total_tokens : 0), 0);
    const samples = responses.flatMap((r) => r.choices)
      .map((c) => { try { return LLM.conform(LLM.parse(c.message.content), recSchema); } catch (e) { return null; } })
      .filter(Boolean);
    if (!samples.length) samples.push(LLM.conform({}, recSchema));

    // Same decisions as "Score and assemble": majority zone, grounded contradictions by majority.
    const counts = {};
    for (const s of samples) counts[s.impact_zone] = (counts[s.impact_zone] || 0) + 1;
    const [zone, votes] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    const lowVotes = samples.filter((s) => s.confidence === 'low').length;
    const abstained = zone === 'unknown' || lowVotes * 2 > samples.length;
    const checks = samples.map((s) => GROUNDING.verifyContradictions(s.internal_contradictions, claim.description));
    const flaggedSamples = checks.filter((c) => c.kept.length > 0).length;
    const contradiction = flaggedSamples * 2 > samples.length;

    const fieldResults = FACT_FIELDS.map(([labelKey, field]) => ({ labelKey, field, value: facts[field], ...checkField(labelKey, facts[field], L) }));
    rows.push({
      claim, facts, dropped, zone, votes, abstained, contradiction,
      contradictionTexts: checks.flatMap((c) => c.kept.map((k) => k.text)),
      rejectedContradictions: checks.flatMap((c) => c.rejected.map((k) => k.text)),
      fieldResults,
      zoneOk: L.zone ? L.zone.includes(zone) : null,
      contradictionOk: contradiction === !!L.contradiction,
      abstainOk: L.abstain ? abstained : null,
    });
    console.log(fieldResults.every((f) => f.ok) && rows[rows.length - 1].contradictionOk ? 'ok' : 'has errors');
  }
  return { name, rows, tokens, recSeconds };
}

function summarize({ name, rows, tokens, recSeconds }) {
  const fields = rows.flatMap((r) => r.fieldResults);
  const zoneRows = rows.filter((r) => r.zoneOk !== null);
  const tp = rows.filter((r) => r.claim.labels.contradiction && r.contradiction).length;
  const fp = rows.filter((r) => !r.claim.labels.contradiction && r.contradiction).length;
  const fn = rows.filter((r) => r.claim.labels.contradiction && !r.contradiction).length;
  const manip = rows.filter((r) => 'manipulation' in r.claim.labels);
  return {
    name,
    claims: rows.length,
    factAccuracy: `${fields.filter((f) => f.ok).length}/${fields.length}`,
    hallucinatedFacts: fields.filter((f) => f.hallucinated).length,
    droppedByGuardrail: rows.reduce((s, r) => s + r.dropped.length, 0),
    zoneAccuracy: `${zoneRows.filter((r) => r.zoneOk).length}/${zoneRows.length}`,
    contradictions: `TP ${tp} / FP ${fp} / FN ${fn}`,
    manipulation: `${manip.filter((r) => r.fieldResults.find((f) => f.labelKey === 'manipulation').ok).length}/${manip.length}`,
    abstention: `${rows.filter((r) => r.abstainOk).length}/${rows.filter((r) => r.abstainOk !== null).length}`,
    tokens,
    secondsPerClaim: Math.round((recSeconds / Math.max(1, rows.length)) * 10) / 10,
  };
}

function report(results) {
  const sums = results.map(summarize);
  const metrics = [
    ['Claims', 'claims'], ['Fact accuracy (fields correct)', 'factAccuracy'],
    ['Invented facts (unlabeled field filled)', 'hallucinatedFacts'], ['Facts dropped by the quote check', 'droppedByGuardrail'],
    ['Impact-zone accuracy', 'zoneAccuracy'], ['Contradictions', 'contradictions'],
    ['Manipulation detected correctly', 'manipulation'], ['Correct abstention on vague claims', 'abstention'],
    ['Tokens used', 'tokens'],
    ['Reconstruction seconds per claim (3 answers, without rate-limit pauses)', 'secondsPerClaim'],
  ];
  let md = `# Prompt evaluation ${MOCK ? '(MOCK RUN — fake answers, not a real result)' : ''}\n\n`;
  md += `Date: ${new Date().toISOString()}  \nExtraction: ${EXT_PROVIDER} (${LLM.PROVIDERS[EXT_PROVIDER].models.extraction}); reconstruction provider and model per column  \n`;
  md += `Test set: dev/eval/claims.json (${results[0].rows.length} claims)\n\n`;
  md += `| Metric | ${sums.map((s) => s.name).join(' | ')} |\n|---|${sums.map(() => '---').join('|')}|\n`;
  for (const [label, key] of metrics) md += `| ${label} | ${sums.map((s) => s[key]).join(' | ')} |\n`;
  for (const res of results) {
    md += `\n## Failures: ${res.name}\n\n`;
    const bad = res.rows.filter((r) => r.fieldResults.some((f) => !f.ok) || !r.contradictionOk || r.zoneOk === false || r.abstainOk === false);
    if (!bad.length) md += 'None.\n';
    for (const r of bad) {
      md += `\n**${r.claim.id}**: ${r.claim.description}\n\n`;
      for (const f of r.fieldResults.filter((x) => !x.ok)) {
        md += `- ${f.field}: got \`${JSON.stringify(f.value)}\`, expected \`${JSON.stringify(r.claim.labels[f.labelKey] ?? 'empty')}\`${f.hallucinated ? ' (invented)' : ''}\n`;
      }
      if (r.zoneOk === false) md += `- impact_zone: got \`${r.zone}\` (${r.votes}/3), expected one of \`${r.claim.labels.zone.join(', ')}\`\n`;
      if (r.abstainOk === false) md += '- should have abstained (unknown zone, low confidence)\n';
      if (!r.contradictionOk) {
        md += `- contradiction: got ${r.contradiction}, expected ${!!r.claim.labels.contradiction}`;
        md += r.contradictionTexts.length ? `; reported: ${r.contradictionTexts.slice(0, 2).join(' | ')}\n` : '\n';
      }
      for (const d of r.dropped) md += `- (guardrail dropped ${d.field}=${JSON.stringify(d.value)}, quote ${JSON.stringify(d.quote)})\n`;
      if (r.rejectedContradictions.length) md += `- (guardrail rejected ${r.rejectedContradictions.length} contradiction(s) with invented quotes)\n`;
    }
  }
  return { md, sums };
}

(async () => {
  const results = [];
  for (const c of CONFIGS) {
    console.log(`Running ${c.extraction} + ${c.reconstruction}`);
    results.push(await runConfig(c));
  }
  const { md, sums } = report(results);
  const dir = path.join(__dirname, 'results');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}${MOCK ? '_MOCK' : ''}.md`);
  fs.writeFileSync(file, md);
  console.table(sums);
  console.log(`Report written to ${file}`);
})().catch((e) => { console.error(e); process.exit(1); });
