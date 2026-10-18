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

// The decision record (design 4.7) + everything needed for the audit log, the result page and Slack.
const R = $('Register Check').first().json;
const input = $('Decision Input').first().json;
const d = $input.first().json || {};
const ok = typeof d.route === 'string';
const policy = input.validation?.policy || {};
const amount = Number(R.claim.claimed_amount);
const route = ok ? d.route : 'human_review';
const payout = route === 'auto_approve'
  ? Math.round(Math.max(0, Math.min(amount - (policy.deductible || 0), policy.coverage_limit ?? Infinity)) * 1000) / 1000 : null;
const record = {
  claim_id: R.claim.claim_id,
  decided_at: new Date().toISOString(),
  processing_seconds: Math.round((Date.now() - Date.parse(R.claim.submitted_at)) / 100) / 10,
  route,
  risk_score: ok ? d.risk_score : null,
  rule_score: ok ? d.rule_score : null,
  llm_adjustment: ok ? d.llm_adjustment : null,
  warning_signs: ok ? d.warning_signs : [],
  route_reasons: ok ? d.route_reasons : [`Decision agent failed: ${String(d.error ?? 'no output')}`],
  coverage: ok ? d.coverage : {},
  justification: ok ? d.justification : '',
  additional_concerns: ok ? d.additional_concerns : [],
  missing_inputs: ok ? d.missing_inputs : [],
  payout_proposed: payout,
  claim: R.claim,
  policy: { policy_id: policy.policy_id, product: policy.product, deductible: policy.deductible,
            coverage_limit: policy.coverage_limit, auto_approval_limit: policy.auto_approval_limit },
  photo_reuse: R.photo_reuse,
  agents: { visual: input.visual, invoice: $('Invoice Parser').first().json, policy_rag: input.policy_rag },
};
return finish(record, R.settings);
