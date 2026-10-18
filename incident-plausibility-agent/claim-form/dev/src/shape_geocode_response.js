// Keeps only what the page needs. Nominatim search returns a list (one n8n item per place);
// reverse returns one object, or {error} when there is no address at that point.
const { mode } = $('Build geocode request').first().json;
const places = $input.all()
  .map((i) => i.json)
  .filter((j) => j && j.lat && j.lon && !j.error);
const pick = (j) => ({ lat: Number(j.lat), lon: Number(j.lon), display_name: j.display_name });

return [{
  json: mode === 'reverse'
    ? { result: places[0] ? pick(places[0]) : null }
    : { results: places.map(pick) },
}];
