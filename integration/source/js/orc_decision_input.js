// Stage 2 of the decision agent: everything the agents found. The invoice is reduced to the contract fields
// (the full extraction is kept in the audit log, not sent to the LLM).
const out = (name) => {
  const j = $(name).first().json;
  return j && Object.keys(j).length ? j : { error: true, reason: `${name}: no output` };
};
const inv = out('Invoice Parser');
const invoice = inv.error ? inv : {
  totals_match: inv.totals_match, arithmetic_issue: inv.arithmetic_issue, line_items: inv.line_items,
  status: inv.status, review_reasons: inv.review_reasons, warnings: inv.warnings,
  amount_matches_claim: inv.amount_matches_claim, total: inv.invoice?.total, currency: inv.invoice?.currency,
};
return [{ json: {
  stage: 'decide',
  claim: $('Register Check').first().json.claim,
  validation: $('Validate Claim').first().json,
  visual: out('Visual Inspection'),
  invoice,
  policy_rag: out('Policy RAG'),
} }];
