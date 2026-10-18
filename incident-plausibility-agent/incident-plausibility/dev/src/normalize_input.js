// Validates the input contract and derives the fields the later nodes need.
// Accepts the claim at the top level, or wrapped as { claim } the way the intake form sends it.
const c = $input.first().json.claim || $input.first().json;

// Optional map pin from the claim form. When present it replaces the typed address,
// which removes the "wrong street with the same name" geocoding problem.
const pinLat = Number.parseFloat(c.incident_lat);
const pinLon = Number.parseFloat(c.incident_lon);
const hasPin = Number.isFinite(pinLat) && Number.isFinite(pinLon)
  && Math.abs(pinLat) <= 90 && Math.abs(pinLon) <= 180;

const required = ['claim_id', 'incident_datetime', 'description'];
const missing = required.filter((k) => !c[k]);
if (!c.incident_location && !hasPin) missing.push('incident_location (or incident_lat + incident_lon)');
if (missing.length) {
  throw new Error(`Incident Plausibility: missing input fields: ${missing.join(', ')}`);
}

// incident_datetime is local time at the incident location, e.g. "2026-03-14T18:40:00".
const dt = String(c.incident_datetime);
const date = dt.slice(0, 10);
const hour = Number(dt.slice(11, 13) || 12);
const minute = Number(dt.slice(14, 16) || 0);
const daysAgo = Math.floor((Date.now() - new Date(`${date}T00:00:00Z`).getTime()) / 86400000);
if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(daysAgo)) {
  throw new Error(`Incident Plausibility: invalid incident_datetime "${dt}"`);
}
if (daysAgo < 0) throw new Error('Incident Plausibility: incident_datetime is in the future');

// The invoice may sit inside the claim or next to it ({ claim, invoice }).
const invoice = c.invoice || $input.first().json.invoice || {};

const NOMINATIM = 'https://nominatim.openstreetmap.org';
const search = (q) => `${NOMINATIM}/search?format=jsonv2&limit=1&q=${encodeURIComponent(q)}`;

return [{
  json: {
    claim_id: c.claim_id,
    incident_date: date,
    incident_hour: hour,
    incident_minutes: hour * 60 + minute,
    days_ago: daysAgo,
    incident_location: c.incident_location ? String(c.incident_location) : null,
    has_pin: hasPin,
    pin_lat: hasPin ? pinLat : null,
    pin_lon: hasPin ? pinLon : null,
    // With a pin, reverse geocoding only fetches a readable address for the evidence text.
    incident_geocode_url: hasPin
      ? `${NOMINATIM}/reverse?format=jsonv2&zoom=17&lat=${pinLat}&lon=${pinLon}`
      : search(String(c.incident_location)),
    // Cap the length so a huge description cannot blow up the prompt cost.
    description: String(c.description).slice(0, 4000),
    invoice_parts: (invoice.line_items || []).map((li) => li.part).filter(Boolean),
  },
}];
