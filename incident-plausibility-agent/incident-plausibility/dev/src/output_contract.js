// Final output of the agent, in the shared ClaimShield format
// (ClaimShield AI/contracts/agent_result.schema.json). The orchestrator's Execute Workflow node
// receives exactly this item, so the Fraud Risk & Decision agent can merge every agent the same way.
const r = $input.first().json;

const WEIGHT = { high: 1, medium: 0.7, low: 0.4 }; // how much a sign counts, by confidence
const signs = r.warning_signs.map((s) => ({ code: s.code, points: s.points, confidence: s.confidence, evidence: s.evidence }));
const score = r.points_total;
const scoreMax = r.points_max;
const weighted = Math.round(signs.reduce((t, s) => t + s.points * (WEIGHT[s.confidence] ?? 1), 0) * 10) / 10;
// This agent's own reading of its score; the decision agent decides the claim's route.
const level = score >= 25 ? 'high' : score >= 10 ? 'medium' : 'low';

const readable = (code) => code.toLowerCase().replace(/_/g, ' ');
const vague = r.reconstruction && r.reconstruction.confidence === 'low';
let summary;
if (signs.length) {
  summary = `${signs.length} warning sign${signs.length > 1 ? 's' : ''}, ${score} points: ${signs.map((s) => readable(s.code)).join('; ')}.`;
} else if (vague) {
  summary = 'No warning signs, but the description is too vague to check: a human should ask the claimant for details.';
} else {
  summary = 'No warning signs: the story is consistent with the map, the weather and the invoice.';
}
if (r.status === 'partial') summary += ' Some checks were skipped (a map or weather service was unavailable).';

return [{
  json: {
    agent: 'incident_plausibility',
    schema_version: '1.0',
    claim_id: r.claim_id,
    status: r.status,
    score,
    score_max: scoreMax,
    score_normalized: scoreMax ? Math.round((score / scoreMax) * 1000) / 1000 : 0,
    weighted_score: weighted,
    agent_risk_level: level,
    warning_signs: signs,
    summary,
    details: {
      prompt_versions: r.prompt_versions,
      reconstruction: r.reconstruction,
      facts: r.facts,
      fact_evidence: r.fact_evidence,
      dropped_facts: r.dropped_facts,
      invoice_check: r.invoice_check,
      context: r.context,
      notes: r.notes,
    },
  },
}];
