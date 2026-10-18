// Visual Inspection Agent input: the claim fields it uses + only the photos (it analyses every file it receives).
const R = $('Register Check').first();
const c = R.json.claim;
const binary = Object.fromEntries(Object.entries(R.binary || {}).filter(([k]) => k.startsWith('photo_')));
return [{ json: { claim_id: c.claim_id, description: c.description, incident_date: c.incident_date, photo_count: c.photo_count }, binary }];
