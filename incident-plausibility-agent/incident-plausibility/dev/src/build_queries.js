// Turns the geocoding result into the Overpass and Open-Meteo queries.
const n = $('Normalize input').first().json;
const place = $('Geocode incident').first().json; // {} when Nominatim found nothing

const num = (v) => (Number.isFinite(Number.parseFloat(v)) ? Number.parseFloat(v) : null);
const lat = n.has_pin ? n.pin_lat : num(place.lat);
const lon = n.has_pin ? n.pin_lon : num(place.lon);
const hasLocation = lat !== null && lon !== null;
// place_rank >= 26 means street level or finer. A city-level match is too coarse
// to say whether a roundabout or traffic light is "there". A map pin is always precise.
const streetLevel = hasLocation && (n.has_pin || Number(place.place_rank) >= 26);

const R = 150; // metres around the incident point
const overpassQuery = `[out:json][timeout:20];(
way(around:${R},${lat},${lon})[highway];
node(around:${R},${lat},${lon})[highway~"^(traffic_signals|stop|give_way|mini_roundabout)$"];
nwr(around:${R},${lat},${lon})[amenity~"^(parking|fuel)$"];
);out tags;`;

// Public Overpass servers are often overloaded (502/504) or slow. The workflow tries them in
// this order, each with a short timeout, and continues without map checks if all fail.
const overpassUrls = [
  'https://overpass-api.de/api/interpreter',
  'https://overpass.private.coffee/api/interpreter',
  'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
];

// The archive API lags about 5 days behind real time; recent incidents use the forecast API.
const base = n.days_ago > 5
  ? 'https://archive-api.open-meteo.com/v1/archive'
  : 'https://api.open-meteo.com/v1/forecast';
const weatherUrl = `${base}?latitude=${lat}&longitude=${lon}`
  + `&start_date=${n.incident_date}&end_date=${n.incident_date}`
  + '&hourly=temperature_2m,precipitation,rain,snowfall,weather_code'
  + '&daily=sunrise,sunset&timezone=auto';

return [{
  json: {
    has_location: hasLocation,
    street_level: streetLevel,
    location_source: n.has_pin ? 'map_pin' : hasLocation ? 'geocoded_address' : 'none',
    lat,
    lon,
    display_name: place.display_name || null,
    place_rank: place.place_rank ?? null,
    overpass_query: overpassQuery,
    overpass_urls: overpassUrls,
    weather_url: weatherUrl,
  },
}];
