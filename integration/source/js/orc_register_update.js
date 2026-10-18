// Add this claim's photos to the register so a later claim reusing them is detected.
const r = $input.first().json;
const R = $('Register Check').first().json;
const register = [...(R.photo_register || [])];
for (const c of R.photo_checks || []) {
  if (!register.some((x) => x.fingerprint === c.fingerprint && x.claim_id === r.claim_id)) {
    register.push({ fingerprint: c.fingerprint, claim_id: r.claim_id, file_name: c.file_name, taken_date: c.taken_date, added_at: new Date().toISOString() });
  }
}
return [{ json: { photos_in_register: register.length },
          binary: { register: { data: Buffer.from(JSON.stringify(register, null, 1), 'utf8').toString('base64'), mimeType: 'application/json', fileName: 'photo_register.json' } } }];
