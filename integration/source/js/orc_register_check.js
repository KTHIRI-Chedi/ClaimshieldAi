// Compare the photo fingerprints with the photos of every earlier claim (data/claimshield/photo_register.json).
const P = $('Photo Checks').first();
let register = [];
try {
  if ($input.first().binary?.data) {
    const r = JSON.parse((await this.helpers.getBinaryDataBuffer(0, 'data')).toString('utf8'));
    if (Array.isArray(r)) register = r;
  }
} catch (e) { register = []; }   // no register yet (first claim) or unreadable: nothing to compare
const claim = { ...P.json.claim };
const checks = P.json.photo_checks || [];
const reuse = [];
for (const c of checks) {
  const hit = register.find((r) => r.fingerprint === c.fingerprint && r.claim_id !== claim.claim_id);
  if (hit) reuse.push({ file_name: c.file_name, already_used_in: hit.claim_id });
}
claim.photo_taken_dates = checks.map((c) => c.taken_date).filter(Boolean);
claim.photo_reused = reuse.length > 0;
return [{ json: { ...P.json, claim, photo_reuse: reuse, photo_register: register }, binary: P.binary }];
