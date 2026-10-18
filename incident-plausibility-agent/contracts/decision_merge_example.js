// Example n8n Code node for the Fraud Risk & Decision agent: combines the results of all agents
// that follow contracts/agent_result.schema.json. Adapt the names to your workflow.
//
// In the orchestrator: send every agent's Execute Workflow output into one Merge node
// (mode "Append"), then into this Code node ("Run Once for All Items").
// The design's limits: rule score max 60, LLM adjustment max 40 (added later by the LLM step).
const RULE_SCORE_MAX = 60;
const results = $input.all().map((i) => i.json).filter((r) => r && r.agent);

// One result per agent (keep the last if an agent appears twice).
const byAgent = {};
for (const r of results) byAgent[r.agent] = r;

// A failed agent must not look like "no risk": flag it for a human.
const failed = Object.values(byAgent).filter((r) => r.status === 'failed').map((r) => r.agent);
const partial = Object.values(byAgent).filter((r) => r.status === 'partial').map((r) => r.agent);

// All warning signs, tagged with the agent that raised them.
const signs = Object.values(byAgent).flatMap((r) => r.warning_signs.map((s) => ({ ...s, agent: r.agent })));

// Avoid counting the same evidence twice: if two agents raise the same code for the same part,
// keep the higher one. (Example: the invoice parser's "part not visible in photos" and the
// plausibility agent's INVOICE_PART_IMPLAUSIBLE can name the same part. Give both a shared
// `part` field in `evidence` or `details` if you want this to be exact.)
const ruleScoreRaw = signs.reduce((t, s) => t + s.points, 0);
const ruleScore = Math.min(RULE_SCORE_MAX, ruleScoreRaw);

// Independent warning signs = raised by different agents (the design needs at least two for an
// investigation).
const agentsWithSigns = new Set(signs.map((s) => s.agent)).size;

return [{
  json: {
    claim_id: results[0] ? results[0].claim_id : null,
    rule_score: ruleScore,
    rule_score_uncapped: ruleScoreRaw,
    warning_signs: signs,
    independent_agents_with_signs: agentsWithSigns,
    agents: Object.fromEntries(Object.entries(byAgent).map(([k, r]) => [k, { status: r.status, score: r.score, summary: r.summary }])),
    needs_human_review: failed.length > 0,
    failed_agents: failed,
    partial_agents: partial,
  },
}];
