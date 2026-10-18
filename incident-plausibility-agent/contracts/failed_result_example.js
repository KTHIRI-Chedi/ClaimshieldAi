// Example n8n Code node for the orchestrator: turns an agent's ERROR into a result in the shared
// format, so the decision agent still gets one result per agent.
//
// Setup: on the Execute Workflow node that calls an agent, open Settings → On Error →
// "Continue (using error output)". Connect that node's error output to this Code node, then
// into the same Merge node as the normal output.
const AGENT = 'incident_plausibility'; // change per agent
const claimId = $('Create claim').first().json.claim.claim_id; // adapt to your node name
const err = $input.first().json.error || {};

return [{
  json: {
    agent: AGENT,
    schema_version: '1.0',
    claim_id: claimId,
    status: 'failed',
    score: 0,
    score_max: 0,
    score_normalized: 0,
    weighted_score: 0,
    agent_risk_level: 'low',
    warning_signs: [],
    summary: `${AGENT} could not run: ${err.message || 'unknown error'}. A human must review this part of the claim.`,
    details: { error: err },
  },
}];
