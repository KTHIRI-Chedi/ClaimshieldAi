// Runs the Code nodes of the BUILT workflow (../incident_plausibility_agent.json) in order,
// outside n8n: real map/weather APIs, mocked LLM answers. Usage: see tests.js.
// Rebuild first after editing src/ or prompts/: python build.py ../incident_plausibility_agent.json
const fs = require('fs');
const path = require('path');

const WORKFLOW = path.join(__dirname, '..', 'incident_plausibility_agent.json');
const NODES = Object.fromEntries(JSON.parse(fs.readFileSync(WORKFLOW, 'utf8')).nodes.map((nd) => [nd.name, nd]));
const out = {};
const $ = (name) => {
  if (!(name in out)) throw new Error(`Node '${name}' hasn't been executed`);
  return { first: () => out[name][0] };
};

// Executes one Code node the way n8n does (body of an async function).
async function runCode(nodeName, input, patch = (s) => s) {
  const code = patch(NODES[nodeName].parameters.jsCode);
  const fn = new Function('$', '$input', `return (async () => {${code}\n})();`);
  return fn($, { first: () => input[0] });
}

const UA = { 'User-Agent': 'ClaimShieldAI-student-project/0.1', 'Accept-Language': 'en' };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function getJson(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) return { error: `HTTP ${r.status}` };
  return r.json();
}
// n8n splits an array response into items; alwaysOutputData turns "no items" into {}.
async function nominatim(url) {
  if (!url) return { error: 'empty URL' };
  const a = await getJson(url, { headers: UA });
  if (Array.isArray(a)) return a.length ? a[0] : {};
  return a;
}

/**
 * claim: input object (null = the Sample claim node)
 * extraction: the mocked answer of "Extract facts (LLM)"
 * reconstructions: the mocked n = 3 answers of "Reconstruct incident x3 (LLM)"
 */
async function main({ claim, extraction, reconstructions, rawReconstructions, quiet }) {
  for (const k of Object.keys(out)) delete out[k];
  out['Sample claim'] = claim ? [{ json: claim }] : await runCode('Sample claim', []);
  out['Normalize input'] = await runCode('Normalize input', out['Sample claim']);
  const n = out['Normalize input'][0].json;
  out['LLM settings'] = await runCode('LLM settings', []);

  out['Geocode incident'] = [{ json: await nominatim(n.incident_geocode_url) }];

  out['Build queries'] = await runCode('Build queries', []);
  const q = out['Build queries'][0].json;

  if (q.has_location) {
    // Same as the workflow: main server, then the mirrors, one try each with a timeout.
    const NAMES = ['Road context (Overpass)', 'Road context (mirror 1)', 'Road context (mirror 2)'];
    const TIMEOUTS = [15000, 15000, 30000];
    for (let i = 0; i < NAMES.length; i += 1) {
      let o;
      try {
        o = await getJson(q.overpass_urls[i], {
          method: 'POST',
          headers: { ...UA, 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ data: q.overpass_query }),
          signal: AbortSignal.timeout(TIMEOUTS[i]),
        });
      } catch (e) { o = { error: e.name }; }
      out[NAMES[i]] = [{ json: o }];
      if (Array.isArray(o.elements)) break;
    }
    out['Weather (Open-Meteo)'] = [{ json: await getJson(q.weather_url) }];
  }
  out['Build context'] = await runCode('Build context', []);

  out['Build extraction request'] = await runCode('Build extraction request', []);
  const extContent = typeof extraction === 'string' ? extraction : JSON.stringify(extraction);
  out['Extract facts (LLM)'] = [{ json: { choices: [{ message: { content: extContent } }] } }];
  out['Verify extracted facts'] = await runCode('Verify extracted facts', out['Extract facts (LLM)']);
  out['Build reconstruction request'] = await runCode('Build reconstruction request', []);
  // Default: one item holding 3 answers (OpenAI with n = 3). rawReconstructions: one item per
  // call with the raw answer text, like Groq or Gemini (3 separate calls).
  const items = rawReconstructions
    ? rawReconstructions.map((text) => ({ json: { choices: [{ message: { content: text } }] } }))
    : [{ json: { choices: reconstructions.map((a) => ({ message: { content: JSON.stringify(a) } })) } }];
  const llmIn = { first: () => items[0], all: () => items };
  const code = NODES['Score and assemble'].parameters.jsCode;
  const result = (await new Function('$', '$input', `return (async () => {${code}\n})();`)($, llmIn))[0].json;

  const c = result.context;
  console.log(`  location: ${c.location.source}, street_level=${c.location.street_level}, "${c.location.display_name}"`);
  console.log(`  road: ${c.road.data_available ? `${c.road.features.join(', ') || 'no features'}; max ${c.road.max_speed_kmh} km/h (${c.road.speed_source}) from ${c.road.source}` : 'map data unavailable'}`);
  if (!quiet) {
    for (const s of result.warning_signs) console.log(`  + ${String(s.points).padStart(2)}  ${s.code} [${s.confidence}]  ${s.evidence}`);
    for (const note of result.notes) console.log(`  note: ${note}`);
    for (const d of result.dropped_facts) console.log(`  dropped fact: ${d.field}=${d.value} (quote: ${JSON.stringify(d.quote)})`);
  }
  console.log(`  TOTAL ${result.points_total} points, status ${result.status}`);
  // Final node: the shared agent result the orchestrator receives.
  const contract = (await runCode('Plausibility score (output)', [{ json: result }]))[0].json;
  const missing = ['agent', 'schema_version', 'claim_id', 'status', 'score', 'score_max', 'score_normalized',
    'weighted_score', 'agent_risk_level', 'warning_signs', 'summary'].filter((k) => !(k in contract));
  if (missing.length) throw new Error(`output contract is missing: ${missing.join(', ')}`);
  console.log(`  OUTPUT score ${contract.score}/${contract.score_max} (normalized ${contract.score_normalized}, weighted ${contract.weighted_score}, ${contract.agent_risk_level}) - ${contract.summary}`);
  return result;
}

const rec = (zone, parts, extra = {}) => ({
  reasoning: 'r', scenario_type: 'rear_end_struck', impact_zone: zone, expected_parts: parts,
  expected_severity_min: 2, expected_severity_max: 3, internal_contradictions: [], confidence: 'high', ...extra,
});
const facts = (extra = {}) => ({
  vehicle_state: 'unknown', maneuver: null, other_party: 'unknown', collision_direction: 'unknown',
  stated_speed_kmh: null, stated_weather: null, stated_light: null, stated_road_features: [], summary: 's',
  manipulation_attempt: false, manipulation_quote: null, ...extra,
});

module.exports = { main, rec, facts };
