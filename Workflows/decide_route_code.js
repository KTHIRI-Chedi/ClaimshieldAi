// Combines the rule score with the LLM adjustment and picks the route.
// Thresholds from section 4.6; move them to a config table later.
const CONFIG = {
  auto_approve_below: 20,
  investigate_at: 50,
  min_signs_for_investigation: 2,
  llm_max: 40,
};

const rules = $('Rule Score').all();

return $input.all().map((item, i) => {
  const base = rules[i].json;

  // Some models write their reasoning (<think>...</think>) or extra text
  // around the JSON, so look for the last object that has llm_adjustment.
  const llm_raw = String(item.json.text ?? item.json.output ?? '');
  const raw = llm_raw
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/```json|```/g, '')
    .trim();
  let llm = { llm_adjustment: 0, justification: '', additional_concerns: [] };
  let llm_error = null;
  let parsed = null;
  const candidates = [raw, ...(raw.match(/\{[^{}]*\}/g) || []).reverse()];
  for (const c of candidates) {
    try {
      const p = JSON.parse(c);
      if (p && typeof p === 'object' && 'llm_adjustment' in p) { parsed = p; break; }
    } catch (e) { /* try the next candidate */ }
  }
  if (parsed) llm = { ...llm, ...parsed };
  else llm_error = llm_raw.trim() ? 'LLM output did not contain the expected JSON (see llm_raw)' : 'LLM returned an empty answer';

  let adj = Math.round(Number(llm.llm_adjustment));
  if (!Number.isFinite(adj)) adj = 0;
  adj = Math.max(0, Math.min(adj, CONFIG.llm_max));
  // The design requires every LLM adjustment to be justified in writing.
  if (adj > 0 && !String(llm.justification || '').trim()) adj = 0;

  const risk = Math.min(base.rule_score + adj, 100);
  const policy = base.validation?.policy || {};
  const amount = Number(base.claim?.claimed_amount);
  const limit = Number(policy.auto_approval_limit ?? 0);
  const coverage = base.policy_rag?.coverage_status ?? 'UNKNOWN';
  const signs = base.warning_signs;
  const reused = signs.some(s => s.code === 'PHOTO_REUSED');

  // Investigation needs a reused photo or two independent rule-based signs,
  // so the LLM can never trigger an investigation on its own.
  let route;
  const route_reasons = [];
  if (reused) {
    route = 'fraud_investigation';
    route_reasons.push('Reused photo');
  } else if (risk >= CONFIG.investigate_at && signs.length >= CONFIG.min_signs_for_investigation) {
    route = 'fraud_investigation';
    route_reasons.push(`Risk score ${risk} with ${signs.length} warning signs`);
  } else {
    if (risk >= CONFIG.auto_approve_below) route_reasons.push(`Risk score ${risk} is ${CONFIG.auto_approve_below} or above`);
    if (!(amount <= limit)) route_reasons.push(`Amount ${amount} is above the auto-approval limit ${limit}`);
    if (coverage !== 'COVERED') route_reasons.push(`Coverage result is ${coverage}`);
    if (base.missing_inputs.length) route_reasons.push(`Missing agent results: ${base.missing_inputs.join(', ')}`);
    if (llm_error) route_reasons.push('LLM assessment failed');
    route = route_reasons.length ? 'human_review' : 'auto_approve';
    if (route === 'auto_approve') route_reasons.push(`Risk score ${risk} below ${CONFIG.auto_approve_below}, amount within limit, covered`);
  }

  return {
    json: {
      stage: 'decide',
      claim_id: base.claim?.claim_id,
      route,
      route_reasons,
      risk_score: risk,
      rule_score: base.rule_score,
      llm_adjustment: adj,
      warning_signs: signs,
      coverage: {
        status: coverage,
        cited_clauses: base.policy_rag?.cited_clauses ?? [],
        reasoning: base.policy_rag?.reasoning ?? '',
      },
      justification: llm.justification,
      additional_concerns: llm.additional_concerns ?? [],
      missing_inputs: base.missing_inputs,
      llm_error,
      llm_raw: llm_error ? llm_raw.slice(0, 3000) : undefined,
      decided_at: new Date().toISOString(),
    },
  };
});
