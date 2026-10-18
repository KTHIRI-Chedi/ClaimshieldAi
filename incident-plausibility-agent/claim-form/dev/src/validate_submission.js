// Server-side check of the submitted claim. Never trust the page's own checks: anyone can
// post to the webhook directly.
const item = $input.first();
const b = (item.json && item.json.body) || {};
const bin = item.binary || {};
const errors = [];

const text = (k, max = 500) => String(b[k] ?? '').trim().slice(0, max);
const MAX_PHOTOS = 8;
const MAX_PHOTO_BYTES = 5 * 1024 * 1024;   // the page sends resized photos of ~0.3-1 MB
const MAX_INVOICE_BYTES = 8 * 1024 * 1024;
const CLAIM_TYPES = ['collision', 'vandalism', 'glass'];

const policyId = text('policy_id', 30).toUpperCase();
if (!/^[A-Z0-9-]{4,30}$/.test(policyId)) errors.push('Policy number is missing or invalid.');

const email = text('contact_email', 200);
if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.push('Email address is missing or invalid.');

const claimType = text('claim_type', 20);
if (!CLAIM_TYPES.includes(claimType)) errors.push('Type of damage is missing or invalid.');

// datetime-local sends "YYYY-MM-DDTHH:MM" in the claimant's local time.
const dt = text('incident_datetime', 25);
if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(dt)) {
  errors.push('Date and time of the incident are missing or invalid.');
} else {
  const asUtc = Date.parse(`${dt.slice(0, 16)}:00Z`);
  // Allow 14 h ahead of UTC (the largest timezone offset), and at most one year back.
  if (asUtc > Date.now() + 14 * 3600 * 1000) errors.push('The incident date cannot be in the future.');
  if (asUtc < Date.now() - 365 * 86400 * 1000) errors.push('The incident is more than a year old. Please contact us.');
}

const description = text('description', 4000);
if (description.length < 20) errors.push('Please describe the incident in at least 20 characters.');

const amount = Number(text('claimed_amount', 20));
if (!(amount > 0 && amount <= 1000000)) errors.push('Claimed amount is missing or invalid.');

const lat = Number.parseFloat(b.incident_lat);
const lon = Number.parseFloat(b.incident_lon);
if (!(Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180)) {
  errors.push('Incident location is missing. Place a pin on the map.');
}

if (!['true', 'on', '1'].includes(text('consent', 5).toLowerCase())) {
  errors.push('You must confirm the declaration.');
}

// ---- Files ----
// n8n names uploaded files after the form field: "photos" for one file, "photos0",
// "photos1"... for several.
const sizeOf = (f) => {
  const m = String(f.fileSize || '').match(/([\d.]+)\s*(B|kB|KB|MB|GB)/);
  if (!m) return 0;
  const unit = { B: 1, kB: 1e3, KB: 1024, MB: 1e6, GB: 1e9 }[m[2]];
  return Number(m[1]) * unit;
};
const keys = Object.keys(bin);
const photoKeys = keys.filter((k) => /^photos\d*$/.test(k))
  .sort((x, y) => Number(x.slice(6) || 0) - Number(y.slice(6) || 0));
const invoiceKeys = keys.filter((k) => /^invoice\d*$/.test(k));

if (photoKeys.length < 1 || photoKeys.length > MAX_PHOTOS) {
  errors.push(`Add between 1 and ${MAX_PHOTOS} damage photos.`);
}
for (const k of photoKeys) {
  if (!['image/jpeg', 'image/png'].includes(bin[k].mimeType)) errors.push(`Photo "${bin[k].fileName}" is not a JPG or PNG.`);
  else if (sizeOf(bin[k]) > MAX_PHOTO_BYTES) errors.push(`Photo "${bin[k].fileName}" is too large.`);
}
if (invoiceKeys.length !== 1) {
  errors.push('Add exactly one repair invoice or quote (PDF).');
} else {
  const inv = bin[invoiceKeys[0]];
  if (inv.mimeType !== 'application/pdf') errors.push('The invoice must be a PDF.');
  else if (sizeOf(inv) > MAX_INVOICE_BYTES) errors.push('The invoice PDF must be smaller than 8 MB.');
}

if (errors.length) return [{ json: { valid: false, errors } }];

// Rename the files to stable names for the agents: photo_1 ... photo_n, invoice.
const binary = {};
photoKeys.forEach((k, i) => { binary[`photo_${i + 1}`] = bin[k]; });
binary.invoice = bin[invoiceKeys[0]];

return [{
  json: {
    valid: true,
    submission: {
      policy_id: policyId,
      contact_email: email,
      claim_type: claimType,
      incident_datetime: `${dt.slice(0, 16)}:00`,
      incident_lat: Number(lat.toFixed(6)),
      incident_lon: Number(lon.toFixed(6)),
      incident_location: text('incident_location', 300) || null,
      description,
      claimed_amount: Math.round(amount * 1000) / 1000,
      currency: 'TND',
      photo_count: photoKeys.length,
    },
  },
  binary,
}];
