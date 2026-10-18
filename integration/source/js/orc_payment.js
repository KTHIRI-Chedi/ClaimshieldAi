// Mock payment endpoint (real payments are out of scope, design 1.3): the request is recorded only.
const r = $input.first().json;
return [{ json: { payment_request: { claim_id: r.claim_id, amount: r.payout_proposed, currency: 'TND', status: 'mock_sent', at: new Date().toISOString() } } }];
