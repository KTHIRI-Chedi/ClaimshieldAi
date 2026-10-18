// __LLM__
// __GROUNDING__
// Votes over the 3 reconstruction samples, runs the deterministic checks and builds the
// agent's output. The LLM interprets the story; every pass/fail decision is made here in code.
const n = $('Normalize input').first().json;
const ctx = $('Build context').first().json;
const { facts, parts_vocabulary: PARTS } = $('Build reconstruction request').first().json;

// Starting values, to calibrate on the labeled test set.
const POINTS = {
  PLACE_FEATURE_MISSING: 10,
  SPEED_IMPLAUSIBLE: 10,
  WEATHER_OR_LIGHT_CONTRADICTION: 15,
  INTERNAL_CONTRADICTION: 10,
  INVOICE_PART_IMPLAUSIBLE: 5,
  INVOICE_PART_IMPLAUSIBLE_MAX: 15,
  MANIPULATION_ATTEMPT: 15,
};
const SPEED_MARGIN_KMH = 40;    // stated speed must exceed the road's limit by this much
const LIGHT_MARGIN_MIN = 45;    // twilight tolerance around sunrise and sunset
const IGNORED_INVOICE_PARTS = ['paint_only', 'other', 'labor'];
// Phrases that address an AI or reviewer. Backs up the LLM's manipulation_attempt flag.
const MANIPULATION_PATTERNS = [
  /ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)/i,
  /(system|developer) (prompt|message|instruction)/i,
  /you are (now )?(an? )?(ai|assistant|language model|chatgpt|gpt)/i,
  /(approve|accept|validate) (this|the|my) claim (automatically|immediately|without)/i,
  /(mark|classify|score) (this|the|my) claim as/i,
  /(risk|fraud) score (of|is|=|should be) ?\d/i,
  /do not (flag|investigate|review)/i,
];

// ---- Self-consistency vote over the samples ----
// One input item per call: 1 item with 3 answers (OpenAI) or 3 items with 1 answer (free providers).
// Each answer is parsed and forced into the schema; an unreadable answer is skipped.
const { schema: recSchema } = $('Build reconstruction request').first().json;
const answerErrors = [];
const contents = $input.all().flatMap((item) => {
  const j = item.json || {};
  if (Array.isArray(j.choices)) return j.choices.map((c) => (c && c.message ? c.message.content : ''));
  try { return [LLM.contentOf(j)]; } catch (e) { answerErrors.push(e.message); return []; }
});
const samples = contents
  .map((text) => { try { return LLM.conform(LLM.parse(text), recSchema); } catch (e) { answerErrors.push(e.message); return null; } })
  .filter(Boolean);
if (!samples.length) {
  throw new Error(`Incident Plausibility: no readable answer from "Reconstruct incident x3 (LLM)". ${answerErrors[0]
    || "The model did not return JSON. Try the provider's larger model in LLM settings."}`);
}

const vote = (key) => {
  const counts = {};
  for (const s of samples) counts[s[key]] = (counts[s[key]] || 0) + 1;
  const [value, votes] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  return { value, votes };
};
const zone = vote('impact_zone');
const scenario = vote('scenario_type');
const agreement = zone.votes / samples.length;
const lowVotes = samples.filter((s) => s.confidence === 'low').length;
let confidence;
if (zone.value === 'unknown' || lowVotes * 2 > samples.length) confidence = 'low';
else if (samples.length < 3) confidence = 'medium'; // too few answers to call it high
else if (agreement === 1) confidence = 'high';
else if (agreement >= 2 / 3) confidence = 'medium';
else confidence = 'low';

const majority = samples.filter((s) => s.impact_zone === zone.value);
const representative = majority[0];
// Union, not intersection: a part counts as expected if any agreeing sample predicted it.
// This keeps the invoice check conservative (fewer false alarms).
const expectedParts = [...new Set(majority.flatMap((s) => s.expected_parts))];

const warningSigns = [];
const notes = [];
// confidence says how much the decision agent can trust the sign:
// high = hard data, medium = good data with known gaps, low = weak signal, review only.
const sign = (code, points, signConfidence, evidence) =>
  warningSigns.push({ code, points, confidence: signConfidence, evidence });

// ---- 1. Described place features exist at the location ----
const stated = facts.stated_road_features || [];
if (stated.length) {
  if (!ctx.location.found) notes.push('Incident location could not be found; place features not checked.');
  else if (!ctx.location.street_level) notes.push('Location is only city-level; place features not checked.');
  else if (!ctx.road.data_available) notes.push('Map data unavailable; place features not checked.');
  else {
    const missing = stated.filter((f) => !ctx.road.features.includes(f));
    if (missing.length) {
      // A typed address can match the wrong street with the same name; a map pin cannot.
      sign('PLACE_FEATURE_MISSING', POINTS.PLACE_FEATURE_MISSING,
        ctx.location.source === 'map_pin' ? 'high' : 'medium',
        `Description mentions ${missing.join(', ')}, but none found within 150 m of "${ctx.location.display_name}"`
        + ` (${ctx.location.source === 'map_pin' ? 'map pin' : 'location from typed address'}).`);
    }
  }
}

// ---- 2. Stated speed is possible on that road ----
if (facts.stated_speed_kmh && ctx.road.max_speed_kmh) {
  if (facts.stated_speed_kmh > ctx.road.max_speed_kmh + SPEED_MARGIN_KMH) {
    sign('SPEED_IMPLAUSIBLE', POINTS.SPEED_IMPLAUSIBLE,
      ctx.road.speed_source === 'osm_tag' ? 'high' : 'medium',
      `Stated speed ${facts.stated_speed_kmh} km/h on roads limited to ${ctx.road.max_speed_kmh} km/h `
      + `(${ctx.road.types.join(', ')}; ${ctx.road.speed_source === 'osm_tag' ? 'signed limit' : 'typical limit for the road type'}).`);
  }
}

// ---- 3. Weather and light match the recorded conditions ----
const weatherIssues = [];
const lightIssues = [];
const w = ctx.weather;
if (facts.stated_weather && w) {
  const codes = w.weather_codes_window;
  const has = (pred) => codes.some(pred);
  const wet = w.precipitation_mm_window > 0.1
    || has((c) => (c >= 51 && c <= 67) || (c >= 80 && c <= 82) || c >= 95);
  const recorded = `recorded ${w.precipitation_mm_window} mm precipitation and "${w.summary_at_incident}" around the incident time`;
  switch (facts.stated_weather) {
    case 'rain':
    case 'storm':
      if (!wet) weatherIssues.push(`Claimant reports ${facts.stated_weather}, but ${recorded}.`);
      break;
    case 'hail':
      if (!wet && !has((c) => c >= 95)) weatherIssues.push(`Claimant reports hail, but ${recorded}.`);
      break;
    case 'snow':
      if (w.snowfall_cm_window === 0 && !has((c) => (c >= 71 && c <= 77) || c === 85 || c === 86)) {
        weatherIssues.push('Claimant reports snow, but recorded snowfall was 0 cm.');
      }
      break;
    case 'ice':
      if (w.min_temp_c_window !== null && w.min_temp_c_window > 3) {
        weatherIssues.push(`Claimant reports ice, but the lowest recorded temperature was ${w.min_temp_c_window} °C.`);
      }
      break;
    case 'fog':
      if (!has((c) => c === 45 || c === 48)) weatherIssues.push('Claimant reports fog, but no fog was recorded.');
      break;
    default:
      break;
  }
}
const L = ctx.light;
if (facts.stated_light && L) {
  const m = n.incident_minutes;
  const fullDay = m > L.sunrise_min + LIGHT_MARGIN_MIN && m < L.sunset_min - LIGHT_MARGIN_MIN;
  const fullNight = m < L.sunrise_min - LIGHT_MARGIN_MIN || m > L.sunset_min + LIGHT_MARGIN_MIN;
  if (facts.stated_light === 'dark' && fullDay) {
    lightIssues.push(`Claimant says it was dark, but the incident time is in daylight (sunrise ${L.sunrise}, sunset ${L.sunset}).`);
  }
  if (facts.stated_light === 'daylight' && fullNight) {
    lightIssues.push(`Claimant says it was daylight, but the incident time is at night (sunrise ${L.sunrise}, sunset ${L.sunset}).`);
  }
}
if (facts.stated_weather && !w) notes.push('Weather data unavailable; weather not checked.');
// Weather and light are one warning sign: two readings of the same "conditions" claim.
// Sunrise/sunset is exact; the weather grid (about 10-25 km) can miss a local shower.
if (weatherIssues.length || lightIssues.length) {
  sign('WEATHER_OR_LIGHT_CONTRADICTION', POINTS.WEATHER_OR_LIGHT_CONTRADICTION,
    lightIssues.length ? 'high' : 'medium', [...weatherIssues, ...lightIssues].join(' '));
}

// ---- 4. The description contradicts itself (majority of samples must agree) ----
// Only contradictions whose two quotes are really in the description count.
const contradictionChecks = samples.map((s) => GROUNDING.verifyContradictions(s.internal_contradictions, n.description));
const rejectedContradictions = contradictionChecks.flatMap((c) => c.rejected.map((r) => r.text));
if (rejectedContradictions.length) {
  notes.push(`Ignored ${rejectedContradictions.length} contradiction(s) whose quotes are not in the description.`);
}
const flagged = contradictionChecks.filter((c) => c.kept.length > 0);
if (flagged.length * 2 > samples.length) {
  sign('INTERNAL_CONTRADICTION', POINTS.INTERNAL_CONTRADICTION,
    flagged.length === samples.length && samples.length >= 3 ? 'high' : 'medium', flagged[0].kept.map((k) => k.text).join(' '));
}

// ---- 5. The description tries to manipulate the AI or the reviewer ----
const patternHit = MANIPULATION_PATTERNS.map((re) => n.description.match(re)).find(Boolean);
if (facts.manipulation_attempt || patternHit) {
  const quote = facts.manipulation_quote || (patternHit && patternHit[0]);
  sign('MANIPULATION_ATTEMPT', POINTS.MANIPULATION_ATTEMPT,
    facts.manipulation_attempt && patternHit ? 'high' : 'medium',
    `The description contains text addressed to the assessment system: "${quote}".`);
}

// ---- 6. Invoiced parts fit the reconstructed scenario ----
const known = n.invoice_parts.filter((p) => PARTS.includes(p));
const unmapped = n.invoice_parts.filter((p) => !PARTS.includes(p) && !IGNORED_INVOICE_PARTS.includes(p));
if (unmapped.length) notes.push(`Invoice parts outside the shared vocabulary, not checked: ${unmapped.join(', ')}.`);
let implausibleParts = [];
if (confidence === 'low') {
  if (known.length) notes.push('Reconstruction confidence is low; invoice parts not checked against the scenario.');
} else {
  implausibleParts = known.filter((p) => !expectedParts.includes(p));
  if (implausibleParts.length) {
    sign('INVOICE_PART_IMPLAUSIBLE',
      Math.min(implausibleParts.length * POINTS.INVOICE_PART_IMPLAUSIBLE, POINTS.INVOICE_PART_IMPLAUSIBLE_MAX),
      confidence,
      `Invoice includes ${implausibleParts.join(', ')}, which a ${scenario.value} with ${zone.value} impact would not damage.`);
  }
}

const checked = ctx.location.found && ctx.weather !== null && ctx.road.data_available;
return [{
  json: {
    agent: 'incident_plausibility',
    prompt_versions: {
      extraction: $('Build extraction request').first().json.prompt_version,
      reconstruction: $('Build reconstruction request').first().json.prompt_version,
    },
    claim_id: n.claim_id,
    status: checked ? 'ok' : 'partial',
    facts,
    // Facts the extraction LLM gave without a supporting quote; dropped before any check.
    fact_evidence: $('Verify extracted facts').first().json.evidence,
    dropped_facts: $('Verify extracted facts').first().json.dropped_facts,
    reconstruction: {
      scenario_type: scenario.value,
      impact_zone: zone.value,
      expected_parts: expectedParts,
      expected_severity_range: [representative.expected_severity_min, representative.expected_severity_max],
      confidence,
      agreement: `${zone.votes}/${samples.length}`,
      reasoning: representative.reasoning,
    },
    context: ctx,
    invoice_check: { implausible_parts: implausibleParts, unmapped_parts: unmapped },
    warning_signs: warningSigns,
    points_total: warningSigns.reduce((s, x) => s + x.points, 0),
    // Highest possible total: every sign once, invoice parts at their cap.
    points_max: POINTS.PLACE_FEATURE_MISSING + POINTS.SPEED_IMPLAUSIBLE + POINTS.WEATHER_OR_LIGHT_CONTRADICTION
      + POINTS.INTERNAL_CONTRADICTION + POINTS.MANIPULATION_ATTEMPT + POINTS.INVOICE_PART_IMPLAUSIBLE_MAX,
    notes,
  },
}];
