// Grounding checks: is a quote the LLM gave us really in the claimant's description?
// Used by "Verify extracted facts", "Score and assemble" and dev/eval/run_eval.js.
const GROUNDING = (() => {
  // Lowercase, unify Unicode forms, drop Arabic diacritics and punctuation.
  const norm = (s) => String(s || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[ً-ْـ]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();

  // Exact (normalized) substring, or at least 80% of the quote's words present: tolerates a
  // dropped article or a typo fix, but not an invented sentence.
  const supported = (quote, text) => {
    const q = norm(quote);
    const t = norm(text);
    if (!q) return false;
    if (t.includes(q)) return true;
    const words = q.split(' ').filter((w) => w.length > 1);
    if (words.length < 3) return false;
    const have = new Set(t.split(' '));
    return words.filter((w) => have.has(w)).length / words.length >= 0.8;
  };

  // Turns a grounded extraction (extraction-v3, with *_quote fields) into the flat fact
  // shape the rest of the agent uses, dropping every fact whose quote is not supported.
  // An ungrounded extraction (extraction-v2) passes through unchanged.
  const verifyFacts = (raw, description) => {
    const grounded = Object.prototype.hasOwnProperty.call(raw, 'stated_weather_quote');
    const facts = { ...raw };
    const dropped = [];
    const evidence = {};
    if (!grounded) return { facts, dropped, evidence, grounded };

    const check = (field, quoteField, emptyValue) => {
      const value = raw[field];
      const quote = raw[quoteField];
      delete facts[quoteField];
      if (value === null || value === emptyValue) return;
      if (supported(quote, description)) {
        evidence[field] = quote;
      } else {
        facts[field] = emptyValue;
        dropped.push({ field, value, quote });
      }
    };
    check('vehicle_state', 'vehicle_state_quote', 'unknown');
    check('collision_direction', 'collision_direction_quote', 'unknown');
    check('stated_speed_kmh', 'stated_speed_quote', null);
    check('stated_weather', 'stated_weather_quote', null);
    check('stated_light', 'stated_light_quote', null);

    const features = [];
    for (const rf of raw.stated_road_features || []) {
      if (supported(rf.quote, description)) {
        features.push(rf.feature);
        evidence[`road_feature:${rf.feature}`] = rf.quote;
      } else {
        dropped.push({ field: 'stated_road_features', value: rf.feature, quote: rf.quote });
      }
    }
    facts.stated_road_features = [...new Set(features)];

    if (raw.manipulation_attempt) {
      if (supported(raw.manipulation_quote, description)) {
        evidence.manipulation = raw.manipulation_quote;
      } else {
        facts.manipulation_attempt = false;
        facts.manipulation_quote = null;
        dropped.push({ field: 'manipulation_attempt', value: true, quote: raw.manipulation_quote });
      }
    }
    return { facts, dropped, evidence, grounded };
  };

  // Keeps only contradictions whose two quotes are both in the description and different.
  // reconstruction-v1 returns plain strings, which cannot be checked and are kept as is.
  const verifyContradictions = (list, description) => {
    const kept = [];
    const rejected = [];
    for (const c of list || []) {
      if (typeof c === 'string') { kept.push({ text: c, grounded: false }); continue; }
      const ok = supported(c.quote_a, description) && supported(c.quote_b, description)
        && norm(c.quote_a) !== norm(c.quote_b);
      (ok ? kept : rejected).push({
        text: `"${c.quote_a}" vs "${c.quote_b}": ${c.explanation}`, grounded: ok,
      });
    }
    return { kept, rejected };
  };

  return { norm, supported, verifyFacts, verifyContradictions };
})();
