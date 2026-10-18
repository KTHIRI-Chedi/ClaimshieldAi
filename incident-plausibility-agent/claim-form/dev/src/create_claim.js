// Gives the claim its ID and builds the record the orchestrator works from.
// If you use an Airtable autonumber for claim IDs instead, create the Airtable row here
// and take the ID from it.
const item = $input.first();
const year = new Date().getUTCFullYear();
const stamp = Date.now().toString(36).slice(-5).toUpperCase();
const rand = Math.random().toString(36).slice(2, 5).toUpperCase();
const claimId = `CLM-${year}-${stamp}${rand}`;

return [{
  json: {
    claim: {
      claim_id: claimId,
      status: 'processing',
      received_at: new Date().toISOString(),
      ...item.json.submission,
    },
  },
  binary: item.binary, // photo_1 ... photo_n and invoice, for the agents
}];
