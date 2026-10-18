// Two photo checks that no agent does (design 4.6):
//  - the date each photo was taken, read from its EXIF data  -> PHOTO_BEFORE_INCIDENT rule (+15)
//  - a fingerprint of the file, compared later with all earlier claims -> PHOTO_REUSED rule (+40)
const item = $input.first();
const checks = [];
for (const key of Object.keys(item.binary || {}).filter((k) => k.startsWith('photo_'))) {
  const buf = await this.helpers.getBinaryDataBuffer(0, key);
  // 64-bit fingerprint (two FNV-1a passes): the same file always gives the same value
  let a = 0x811c9dc5, b = 0x01000193 ^ buf.length;
  for (let i = 0; i < buf.length; i++) {
    a = Math.imul(a ^ buf[i], 16777619) >>> 0;
    b = Math.imul(b ^ buf[buf.length - 1 - i], 16777619) >>> 0;
  }
  const fingerprint = `${a.toString(16).padStart(8, '0')}${b.toString(16).padStart(8, '0')}-${buf.length}`;
  // EXIF dates are plain text "YYYY:MM:DD HH:MM:SS" at the start of a JPEG; the earliest one is the shot
  const head = buf.subarray(0, Math.min(buf.length, 131072)).toString('latin1');
  const dates = [...head.matchAll(/(\d{4}):(\d{2}):(\d{2}) \d{2}:\d{2}:\d{2}/g)]
    .map((m) => `${m[1]}-${m[2]}-${m[3]}`)
    .filter((d) => d >= '1995-01-01' && !Number.isNaN(Date.parse(d)))
    .sort();
  checks.push({ key, file_name: item.binary[key].fileName || key, fingerprint, taken_date: dates[0] || null });
}
return [{ json: { ...item.json, photo_checks: checks }, binary: item.binary }];
