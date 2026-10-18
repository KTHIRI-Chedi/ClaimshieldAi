// ===== SETTINGS ===================================================================================
const SETTINGS = {
  invoice_technique: 'few_shot',     // prompt technique of the invoice agent (best in the evaluation)
  slack_enabled: false,              // true once a Slack credential is set on the two Slack nodes
  slack_channel: 'claims-review',    // channel name (without #) for review requests and fraud alerts
};
// ==================================================================================================
// One claim format for both entry points (the form and the authenticated API), and the files sorted:
// images -> photo_0, photo_1, ... ; the repair invoice (PDF, or a file whose name says invoice/facture) -> invoice.
const item = $input.first();
const j = item.json || {};
const fromApi = j.headers !== undefined && j.body !== undefined;
const body = fromApi ? (j.body || {}) : j;
const pick = (...keys) => {
  for (const k of keys) {
    const v = body[k];
    if (v !== undefined && v !== null && String(v).trim() !== '' && typeof v !== 'object') return v;
  }
  return undefined;
};
const isInvoiceName = (s) => /invoice|facture|repair/i.test(s || '');
const isImage = (b) => /^image\//i.test(b.mimeType || '') || /\.(jpe?g|png|webp)$/i.test(b.fileName || '');
const isPdf = (b) => /pdf/i.test(b.mimeType || '') || /\.pdf$/i.test(b.fileName || '');
const files = Object.entries(item.binary || {});
let invoiceEntry = files.find(([k, b]) => isInvoiceName(k) || isInvoiceName(b.fileName)) || files.find(([, b]) => isPdf(b));
const binary = {};
let n = 0;
for (const [k, b] of files) {
  if (invoiceEntry && k === invoiceEntry[0]) continue;
  if (isImage(b)) binary[`photo_${n++}`] = b;
}
if (invoiceEntry) binary.invoice = invoiceEntry[1];

const now = new Date();
const amount = pick('claimed_amount', 'Claimed amount (TND)');
const date = pick('incident_date', 'Incident date');
const claim = {
  claim_id: String(pick('claim_id') || `CLM-${now.toISOString().slice(0, 10).replace(/-/g, '')}-${Math.random().toString(36).slice(2, 7).toUpperCase()}`),
  policy_id: String(pick('policy_id', 'Policy ID') ?? '').trim().toUpperCase(),
  incident_date: date ? String(date).slice(0, 10) : undefined,
  incident_location: String(pick('incident_location', 'Incident location') ?? ''),
  description: String(pick('description', 'Description of the accident') ?? ''),
  claimed_amount: amount !== undefined ? Number(String(amount).replace(',', '.')) : undefined,
  photo_count: n,
  has_invoice: !!invoiceEntry,
  source: fromApi ? 'api' : 'form',
  submitted_at: now.toISOString(),
};
return [{ json: { claim, settings: SETTINGS }, binary }];
