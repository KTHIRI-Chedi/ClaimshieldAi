// Summarises the map and weather data into facts the scoring step can check.
// Reached from both branches of "Location found?", so the API nodes may not have run.
const n = $('Normalize input').first().json;
const q = $('Build queries').first().json;
const safe = (name) => {
  try { return $(name).first().json; } catch (e) { return null; }
};
// The first Overpass server that answered with data (main server, then the two mirrors).
const OVERPASS_NODES = ['Road context (Overpass)', 'Road context (mirror 1)', 'Road context (mirror 2)'];
const answered = q.has_location
  ? OVERPASS_NODES.find((name) => { const j = safe(name); return j && Array.isArray(j.elements); })
  : undefined;
const osm = answered ? safe(answered) : null;
const wx = q.has_location ? safe('Weather (Open-Meteo)') : null;

// ---- Road type, speed limit and nearby features (OpenStreetMap) ----
// Typical limits used when a road has no maxspeed tag.
const SPEED_DEFAULTS = {
  motorway: 120, trunk: 100, primary: 90, secondary: 80, tertiary: 70, unclassified: 60,
  residential: 50, living_street: 20, service: 30,
  motorway_link: 80, trunk_link: 70, primary_link: 60, secondary_link: 60,
};
const elements = osm && Array.isArray(osm.elements) ? osm.elements : [];
const ways = elements.filter((e) => e.type === 'way' && e.tags && e.tags.highway);
const speeds = ways
  .map((w) => Number.parseInt(w.tags.maxspeed, 10) || SPEED_DEFAULTS[w.tags.highway])
  .filter(Boolean);
const speedTagged = ways.some((w) => Number.parseInt(w.tags.maxspeed, 10));

const features = new Set();
for (const e of elements) {
  const t = e.tags || {};
  if (t.junction === 'roundabout' || t.highway === 'mini_roundabout') features.add('roundabout');
  if (t.highway === 'traffic_signals') features.add('traffic_light');
  if (['traffic_signals', 'stop', 'give_way'].includes(t.highway)) features.add('intersection');
  if (t.amenity === 'parking' || (t.highway === 'service' && t.service === 'parking_aisle')) features.add('parking_lot');
  if (t.amenity === 'fuel') features.add('fuel_station');
  if (t.bridge && t.bridge !== 'no') features.add('bridge');
  if (t.tunnel && t.tunnel !== 'no') features.add('tunnel');
  if (['motorway', 'trunk', 'motorway_link', 'trunk_link'].includes(t.highway)) features.add('highway');
  if (['residential', 'living_street', 'unclassified', 'service'].includes(t.highway)) features.add('residential_street');
}
// Two differently named roads within the radius means there is a junction nearby.
if (new Set(ways.map((w) => w.tags.name).filter(Boolean)).size >= 2) features.add('intersection');

// ---- Weather around the incident time (Open-Meteo) ----
const WMO = (c) => {
  if (c === null || c === undefined) return null;
  if (c === 0) return 'clear';
  if (c <= 3) return 'cloudy';
  if (c === 45 || c === 48) return 'fog';
  if (c >= 51 && c <= 57) return 'drizzle';
  if (c >= 61 && c <= 67) return 'rain';
  if (c >= 71 && c <= 77) return 'snow';
  if (c >= 80 && c <= 82) return 'rain showers';
  if (c === 85 || c === 86) return 'snow showers';
  if (c === 95) return 'thunderstorm';
  if (c >= 96) return 'thunderstorm with hail';
  return `code ${c}`;
};

let weather = null;
let light = null;
if (wx && wx.hourly && Array.isArray(wx.hourly.time)) {
  const h = wx.hourly;
  const hourOf = (t) => Number(t.slice(11, 13));
  // From 3 hours before to 1 hour after: rain that just stopped still leaves the road wet.
  const idx = h.time
    .map((t, i) => ({ hr: hourOf(t), i }))
    .filter((o) => o.hr >= n.incident_hour - 3 && o.hr <= n.incident_hour + 1)
    .map((o) => o.i);
  const pick = (k) => idx.map((i) => (h[k] || [])[i]).filter((v) => v !== null && v !== undefined);
  const sum = (a) => a.reduce((s, v) => s + v, 0);
  const at = h.time.findIndex((t) => hourOf(t) === n.incident_hour);
  const temps = pick('temperature_2m');
  weather = {
    summary_at_incident: WMO((h.weather_code || [])[at]),
    temp_c_at_incident: (h.temperature_2m || [])[at] ?? null,
    min_temp_c_window: temps.length ? Math.min(...temps) : null,
    precipitation_mm_window: Number(sum(pick('precipitation')).toFixed(1)),
    snowfall_cm_window: Number(sum(pick('snowfall')).toFixed(1)),
    weather_codes_window: [...new Set(pick('weather_code'))],
  };
}
if (wx && wx.daily && wx.daily.sunrise && wx.daily.sunset) {
  const sr = wx.daily.sunrise[0];
  const ss = wx.daily.sunset[0];
  const toMin = (s) => Number(s.slice(11, 13)) * 60 + Number(s.slice(14, 16));
  light = { sunrise: sr.slice(11, 16), sunset: ss.slice(11, 16), sunrise_min: toMin(sr), sunset_min: toMin(ss) };
}

return [{
  json: {
    location: {
      found: q.has_location,
      street_level: q.street_level,
      source: q.location_source,
      display_name: q.display_name,
      lat: q.lat,
      lon: q.lon,
    },
    road: {
      types: [...new Set(ways.map((w) => w.tags.highway))],
      max_speed_kmh: speeds.length ? Math.max(...speeds) : null,
      speed_source: speedTagged ? 'osm_tag' : speeds.length ? 'road_type_default' : null,
      features: [...features],
      data_available: osm !== null,
      source: answered || null,
    },
    weather,
    light,
  },
}];
