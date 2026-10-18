// Policy RAG Agent input: description, the customer's product, the parts seen on the photos and on the invoice.
const out = (name) => {
  const j = $(name).first().json;
  return j && Object.keys(j).length ? j : { error: true, reason: `${name}: no output` };
};
return [{ json: {
  claim: $('Register Check').first().json.claim,
  policy: $('Validate Claim').first().json.policy,
  visual: out('Visual Inspection'),
  invoice: out('Invoice Parser'),
} }];
