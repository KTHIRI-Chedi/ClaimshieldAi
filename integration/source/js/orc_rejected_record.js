// ---- shared by Decision Record and Rejected Record: result page and Slack texts
const LABEL = { auto_approve: 'APPROVED', human_review: 'HUMAN REVIEW', fraud_investigation: 'FRAUD INVESTIGATION', rejected: 'REJECTED' };
const CUSTOMER = {
  auto_approve: (r) => `Your claim ${r.claim_id} is approved. A payment request of ${r.payout_proposed ?? '-'} TND (after the deductible) has been sent.`,
  human_review: (r) => `Your claim ${r.claim_id} has been received and is being reviewed by an adjuster. You will be contacted within 2 working days.`,
  // customer messages never mention suspected fraud (design 4.8)
  fraud_investigation: (r) => `Your claim ${r.claim_id} has been received and needs additional checks by our team. You will be contacted soon.`,
  rejected: (r) => `Your claim ${r.claim_id} cannot be accepted: ${r.route_reasons.join('; ')}.`,
};
function finish(r, settings) {
  const signs = (r.warning_signs || []).map((s) => `${s.code} (+${s.points}): ${s.detail}`);
  const internal = [
    `Route: ${LABEL[r.route] || r.route}` + (r.risk_score != null ? ` | risk score ${r.risk_score}/100 (rules ${r.rule_score} + AI ${r.llm_adjustment})` : ''),
    `Warning signs: ${signs.length ? signs.join(' | ') : 'none'}`,
    r.coverage?.status ? `Coverage: ${r.coverage.status}${(r.coverage.cited_clauses || []).length ? ` (${r.coverage.cited_clauses.join(', ')})` : ''}` : null,
    `Reasons: ${(r.route_reasons || []).join('; ') || '-'}`,
    r.justification ? `AI assessment: ${r.justification}` : null,
    `Processed in ${r.processing_seconds} s`,
  ].filter(Boolean);
  const page = {
    title: `Claim ${r.claim_id} - ${LABEL[r.route] || r.route}`,
    message: `${CUSTOMER[r.route] ? CUSTOMER[r.route](r) : ''}\n\n--- Internal summary (adjuster only) ---\n${internal.join('\n')}`,
  };
  const head = `Claim ${r.claim_id} | policy ${r.claim.policy_id} | ${r.claim.claimed_amount} TND`;
  const slack = {
    review_message: `*Human review needed* - ${head}\n${internal.join('\n')}\nDescription: ${r.claim.description}`,
    fraud_message: `:rotating_light: *Fraud investigation* - ${head}\n${internal.join('\n')}`,
  };
  return [{ json: { ...r, settings, page, slack } }];
}

// A claim rejected by the validation stage (missing field, unknown or inactive policy, incident outside
// the coverage period): no AI call was made.
const R = $('Register Check').first().json;
const v = $input.first().json || {};
const record = {
  claim_id: R.claim.claim_id,
  decided_at: new Date().toISOString(),
  processing_seconds: Math.round((Date.now() - Date.parse(R.claim.submitted_at)) / 100) / 10,
  route: 'rejected',
  risk_score: null, rule_score: null, llm_adjustment: null, warning_signs: [],
  route_reasons: v.reasons?.length ? v.reasons : [`Validation failed: ${String(v.error ?? 'no output')}`],
  coverage: {}, justification: '', additional_concerns: [], missing_inputs: [], payout_proposed: null,
  claim: R.claim, policy: v.policy || null, photo_reuse: R.photo_reuse, agents: {},
};
return finish(record, R.settings);
