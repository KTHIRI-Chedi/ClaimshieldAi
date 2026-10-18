// Address lookup for the claim page, so the browser never calls Nominatim directly.
// ?lat=..&lon=..  -> reverse lookup (pin to address)
// ?q=..           -> search (address to up to 5 places)
const qy = $input.first().json.query || {};
const NOMINATIM = 'https://nominatim.openstreetmap.org';
const lat = Number.parseFloat(qy.lat);
const lon = Number.parseFloat(qy.lon);

let mode = null;
let url = null;
if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
  mode = 'reverse';
  url = `${NOMINATIM}/reverse?format=jsonv2&zoom=18&lat=${lat}&lon=${lon}`;
} else if (typeof qy.q === 'string' && qy.q.trim().length >= 3) {
  mode = 'search';
  url = `${NOMINATIM}/search?format=jsonv2&limit=5&q=${encodeURIComponent(qy.q.trim().slice(0, 200))}`;
}

return [{ json: { mode, url } }];
