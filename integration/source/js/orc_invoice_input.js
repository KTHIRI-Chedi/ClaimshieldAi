// Invoice Parser Agent input: the claim (for its fraud signals) + the invoice file only.
const R = $('Register Check').first();
const c = R.json.claim;
const json = {
  claim: { claim_id: c.claim_id, claimed_amount: c.claimed_amount, incident_date: c.incident_date },
  technique: R.json.settings.invoice_technique,
};
if (!R.binary?.invoice) json.invoice_path = '/data/claimshield/no_invoice_sent.pdf';   // agent answers { error: true }
return [{ json, binary: R.binary?.invoice ? { invoice: R.binary.invoice } : {} }];
