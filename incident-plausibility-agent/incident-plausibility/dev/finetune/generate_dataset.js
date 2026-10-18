// Builds the fine-tuning dataset for the reconstruction step (Qwen2.5-3B + QLoRA).
//
// Each example = system prompt + user message (description + extracted facts) + the target JSON,
// built with the SAME prompt the workflow uses for the fine-tuned model (reconstruction-ft1).
// Labels come from the scenario spec (scenarios.js), so they are correct by construction.
//
// Usage:
//   node dev/finetune/generate_dataset.js                      templates only, no API needed
//   node dev/finetune/generate_dataset.js --paraphrase 300     also let an LLM reword 300 descriptions
//        (needs LLM_API_KEY; --provider groq|gemini|...; protected sentences are kept word for word)
// Options: --train 2000 --valid 150 --test 200 --seed 42 --out dev/finetune/data
const fs = require('fs');
const path = require('path');
const S = require('./scenarios');

const DEV = path.join(__dirname, '..');
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const N_TRAIN = Number(opt('--train', 2000));
const N_VALID = Number(opt('--valid', 150));
const N_TEST = Number(opt('--test', 200));
const SEED = Number(opt('--seed', 42));
const OUT = path.resolve(opt('--out', path.join(__dirname, 'data')));
const N_PARAPHRASE = Number(opt('--paraphrase', 0));
const PROVIDER_NAME = opt('--provider', 'groq');

// Load the shared vocabulary, the grounding check and the fine-tuned model's prompt.
const read = (f) => fs.readFileSync(path.join(DEV, 'prompts', f), 'utf8');
const { VOCAB, GROUNDING, PROMPT, LLM } = new Function(
  `${read('vocabulary.js')}\n${read('grounding.js')}\n${read('llm.js')}\n${read('reconstruction.ft1.js')}\nreturn { VOCAB, GROUNDING, PROMPT, LLM };`,
)();

// ---- Seeded random numbers, so the dataset is reproducible ----
let state = SEED >>> 0;
const rand = () => { state = (state + 0x6D2B79F5) >>> 0; let t = state; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
const pick = (arr) => arr[Math.floor(rand() * arr.length)];
const chance = (p) => rand() < p;
const int = (lo, hi) => lo + Math.floor(rand() * (hi - lo + 1));
const weighted = (items) => {
  const total = items.reduce((s, x) => s + x.weight, 0);
  let r = rand() * total;
  for (const x of items) { r -= x.weight; if (r <= 0) return x; }
  return items[items.length - 1];
};

const LANG_WEIGHTS = [{ v: 'en', weight: 45 }, { v: 'fr', weight: 35 }, { v: 'ar', weight: 20 }];
const fill = (tpl, slots) => tpl.replace(/\{(\w+)\}/g, (_, k) => (slots[k] ?? ''))
  .replace(/\s+([.,;!?،])/g, '$1').replace(/\s{2,}/g, ' ').trim();

function placePhrase(feature, lang) {
  const tpl = S.PLACES[feature][lang];
  const [s, s2] = [pick(S.STREETS[lang]), pick(S.STREETS[lang])];
  return fill(tpl, { s, s2: s2 === s ? S.STREETS[lang][0] : s2, c: pick(S.CITIES[lang]), p: pick(S.PARKINGS[lang]) });
}
const PLACE_EN = {
  traffic_light: ' at a traffic light', roundabout: ' at a roundabout', intersection: ' at a junction',
  parking_lot: ' in a car park', highway: ' on the motorway', street: '',
};

// ---- One example ----
function makeExample() {
  const lang = weighted(LANG_WEIGHTS).v;
  const facts = {
    vehicle_state: 'unknown', maneuver: null, other_party: 'unknown', collision_direction: 'unknown',
    stated_speed_kmh: null, stated_weather: null, stated_light: null, stated_road_features: [],
    summary: '', manipulation_attempt: false, manipulation_quote: null,
  };
  const meta = { lang, flags: [] };
  const sentences = []; // [{ text, protected }] protected = must stay word for word (quoted or injection)

  // Too vague: abstain.
  if (chance(0.07)) {
    meta.scenario = 'vague';
    sentences.push({ text: pick(S.VAGUE[lang]) });
    const extras = [...S.VAGUE_EXTRA[lang]].sort(() => rand() - 0.5).slice(0, int(0, 2));
    for (const e of extras) sentences.push({ text: e });
    facts.summary = 'The claimant reports damage without describing the incident.';
    const answer = {
      reasoning: 'The description does not say how the damage happened or which side of the car was hit, so the incident cannot be reconstructed.',
      scenario_type: 'unknown', impact_zone: 'unknown', expected_parts: [],
      expected_severity_min: 1, expected_severity_max: 5, internal_contradictions: [], confidence: 'low',
    };
    return { sentences, facts, answer, meta };
  }

  const sc = weighted(S.SCENARIOS);
  meta.scenario = sc.id;
  Object.assign(facts, sc.facts);
  facts.summary = sc.summary;

  const side = sc.sided ? pick(['left', 'right']) : null;
  if (side && sc.facts.collision_direction === undefined) facts.collision_direction = side;
  const feature = pick(sc.places);
  if (feature !== 'street') facts.stated_road_features = [feature];
  const speed = sc.speed && chance(0.7) ? Math.round(int(sc.speed[0], sc.speed[1]) / 5) * 5 : null;
  if (speed !== null) facts.stated_speed_kmh = speed;

  const tplRaw = pick(sc.templates[lang]);
  const tpl = typeof tplRaw === 'string' ? { t: tplRaw } : tplRaw;
  const sd = side ? S.SIDES[side] : {};
  const objectList = sc.objects ? sc.objects[lang] : null;
  const main = fill(tpl.t, {
    place: placePhrase(feature, lang),
    v: pick(S.VEHICLES[lang]),
    o: objectList ? pick(objectList) : '',
    speed: speed !== null ? S.speedPhrase[lang].replace('{n}', speed) : '',
    side: sd.en, door: sd.doorEn, sideFr: sd.fr, frDir: sd.frDir, doorFr: sd.doorFr,
    sideAr: sd.ar, arDir: sd.arDir, sideArF: sd.arF, doorAr: sd.doorAr,
  });
  // If the chosen template does not mention the speed, the extraction would not find it.
  if (speed !== null && !main.includes(String(speed))) facts.stated_speed_kmh = null;
  sentences.push({ text: main });

  // Labels from the spec (with per-template overrides, e.g. vandalised windshield).
  const ctx = { side, speed: facts.stated_speed_kmh, placeEn: PLACE_EN[feature] };
  const label = sc.label(ctx);
  const zone = tpl.zone || label.impact_zone;
  const parts = tpl.parts || label.parts;
  ctx.zone = zone;
  ctx.zoneWords = zone === 'windshield' ? 'windshield' : `${side} doors and mirror`;
  ctx.speedEn = facts.stated_speed_kmh ? ` at about ${facts.stated_speed_kmh} km/h` : '';
  let reasoning = sc.reason(ctx);
  let confidence = 'high';
  const contradictions = [];

  // Contradiction (two protected sentences, both quoted in the label).
  const usable = S.CONTRADICTIONS.filter((c) => c.when(sc));
  const contra = usable.length && chance(0.18) ? pick(usable) : null;
  if (contra) {
    meta.flags.push(`contradiction:${contra.id}`);
    const a = contra.a[lang];
    const b = contra.b[lang];
    // Put the two statements at different places in the story.
    sentences.unshift({ text: a, protected: true });
    sentences.push({ text: b, protected: true });
    contradictions.push({ quote_a: a, quote_b: b, explanation: contra.explanation });
    reasoning += ' However, the description contains two statements that cannot both be true.';
    confidence = 'medium';
  }

  // Conditions, light and hedges (facts, not contradictions).
  if (chance(0.2) && sc.id !== 'hail') {
    const w = pick(Object.keys(S.WEATHER));
    sentences.push({ text: S.WEATHER[w][lang] });
    facts.stated_weather = w;
  }
  if (chance(0.15) && !(contra && contra.noLight)) {
    const l = pick(Object.keys(S.LIGHT));
    sentences.push({ text: S.LIGHT[l][lang] });
    facts.stated_light = l;
  }
  if (chance(0.15)) {
    meta.flags.push('hedge');
    sentences.push({ text: pick(S.HEDGES[lang]) });
    reasoning += ' The uncertain details are missing information, not contradictions.';
  }
  // Injection attempt: the reconstruction must not change because of it.
  if (chance(0.05)) {
    meta.flags.push('injection');
    const inj = pick(S.INJECTIONS[lang]);
    sentences.push({ text: inj, protected: true });
    facts.manipulation_attempt = true;
    facts.manipulation_quote = inj;
  }
  // Extraction is not perfect: sometimes a fact is missing and the text must be read.
  if (chance(0.12)) {
    meta.flags.push('fact_dropped');
    if (chance(0.5)) facts.collision_direction = 'unknown'; else facts.stated_road_features = [];
  }

  const answer = {
    reasoning,
    scenario_type: label.scenario_type,
    impact_zone: zone,
    expected_parts: parts,
    expected_severity_min: label.severity[0],
    expected_severity_max: label.severity[1],
    internal_contradictions: contradictions,
    confidence,
  };
  return { sentences, facts, answer, meta };
}

// ---- Optional: let an LLM reword descriptions for more natural variety ----
async function paraphrase(examples) {
  const provider = LLM.PROVIDERS[PROVIDER_NAME];
  const key = process.env.LLM_API_KEY || (PROVIDER_NAME === 'ollama' ? 'ollama' : '');
  if (!key) throw new Error('--paraphrase needs LLM_API_KEY (and --provider).');
  const url = provider.url.replace('host.docker.internal', 'localhost');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let changed = 0;
  for (let i = 0; i < examples.length; i += 5) {
    const batch = examples.slice(i, i + 5);
    const items = batch.map((ex, k) => ({
      id: k,
      language: { en: 'English', fr: 'French', ar: 'Arabic' }[ex.meta.lang],
      text: ex.description,
      keep_exactly: ex.sentences.filter((s) => s.protected).map((s) => s.text),
    }));
    const body = {
      model: provider.models.reconstruction,
      temperature: 0.9,
      messages: [
        { role: 'system', content: 'You rewrite short car-insurance claim descriptions so they sound like real customers wrote them: vary the wording, sentence order and tone, keep the same language, keep every fact (places, speeds, sides, weather), add nothing new. Every sentence listed in keep_exactly must appear unchanged, character for character. Reply with JSON {"items":[{"id":0,"text":"..."}]}.' },
        { role: 'user', content: JSON.stringify({ items }) },
      ],
      response_format: { type: 'json_object' },
      stream: false,
    };
    for (const [m, fields] of Object.entries(provider.extra || {})) if (body.model.includes(m)) Object.assign(body, fields);
    try {
      if (provider.callIntervalMs) await sleep(provider.callIntervalMs);
      const r = await fetch(url, { method: 'POST', headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) { console.log(`  paraphrase batch ${i / 5}: HTTP ${r.status}, kept templates`); continue; }
      const out = LLM.parse(LLM.contentOf(await r.json()));
      for (const it of out.items || []) {
        const ex = batch[it.id];
        // Accept the rewrite only if every protected sentence is still there word for word.
        if (ex && typeof it.text === 'string' && it.text.length > 20
          && ex.sentences.filter((s) => s.protected).every((s) => it.text.includes(s.text))) {
          ex.description = it.text.trim();
          ex.meta.flags.push('paraphrased');
          changed += 1;
        }
      }
      process.stdout.write(`\r  paraphrased ${changed}/${examples.length}`);
    } catch (e) { console.log(`  paraphrase batch ${i / 5}: ${e.message}, kept templates`); }
  }
  console.log('');
}

// ---- Validation: the same checks the workflow applies to model answers ----
function validate(ex) {
  const problems = [];
  const conformed = LLM.conform(ex.answer, PROMPT.schema);
  if (JSON.stringify(conformed) !== JSON.stringify(ex.answer)) problems.push('answer does not match the schema');
  for (const c of ex.answer.internal_contradictions) {
    if (!GROUNDING.supported(c.quote_a, ex.description) || !GROUNDING.supported(c.quote_b, ex.description)) {
      problems.push('contradiction quote not in description');
    }
  }
  return problems;
}

(async () => {
  const total = N_TRAIN + N_VALID + N_TEST;
  const seen = new Set();
  const examples = [];
  let guard = 0;
  while (examples.length < total && guard < total * 20) {
    guard += 1;
    const ex = makeExample();
    ex.description = ex.sentences.map((s) => s.text).join(' ');
    if (seen.has(ex.description)) continue; // no duplicates (and none shared between splits)
    seen.add(ex.description);
    examples.push(ex);
  }

  if (N_PARAPHRASE > 0) {
    console.log(`Paraphrasing ${N_PARAPHRASE} training descriptions with ${PROVIDER_NAME}...`);
    await paraphrase(examples.slice(0, Math.min(N_PARAPHRASE, N_TRAIN)));
  }

  const bad = [];
  const rows = examples.map((ex, i) => {
    const problems = validate(ex);
    if (problems.length) bad.push({ i, problems, description: ex.description });
    return {
      messages: [
        { role: 'system', content: PROMPT.system },
        { role: 'user', content: PROMPT.userMsg(ex.description, ex.facts) },
        { role: 'assistant', content: JSON.stringify(ex.answer) },
      ],
      meta: ex.meta,
    };
  });
  if (bad.length) {
    console.error(`${bad.length} invalid examples, e.g.:`, JSON.stringify(bad.slice(0, 3), null, 1));
    process.exit(1);
  }

  fs.mkdirSync(OUT, { recursive: true });
  const write = (name, list) => fs.writeFileSync(path.join(OUT, name), list.map((r) => JSON.stringify(r)).join('\n') + '\n');
  write('train.jsonl', rows.slice(0, N_TRAIN));
  write('valid.jsonl', rows.slice(N_TRAIN, N_TRAIN + N_VALID));
  write('test.jsonl', rows.slice(N_TRAIN + N_VALID));

  // Summary for the report.
  const count = (list, f) => list.reduce((m, r) => { const k = f(r); m[k] = (m[k] || 0) + 1; return m; }, {});
  const train = rows.slice(0, N_TRAIN);
  const chars = rows.map((r) => r.messages.reduce((s, m) => s + m.content.length, 0));
  const stats = {
    examples: { train: N_TRAIN, valid: N_VALID, test: N_TEST },
    seed: SEED,
    prompt_version: PROMPT.version,
    languages: count(train, (r) => r.meta.lang),
    scenarios: count(train, (r) => r.meta.scenario),
    flags: train.flatMap((r) => r.meta.flags).reduce((m, f) => { const k = f.split(':')[0]; m[k] = (m[k] || 0) + 1; return m; }, {}),
    approx_tokens_per_example: { mean: Math.round(chars.reduce((a, b) => a + b, 0) / chars.length / 3.5), max: Math.round(Math.max(...chars) / 3.5) },
  };
  fs.writeFileSync(path.join(OUT, 'stats.json'), JSON.stringify(stats, null, 2));
  console.log(`Wrote ${OUT}: train ${N_TRAIN}, valid ${N_VALID}, test ${N_TEST}`);
  console.log(JSON.stringify(stats, null, 2));
})().catch((e) => { console.error(e); process.exit(1); });
