// One chunk per policy clause, with a structural header in the chunk text (as in Chedi's ingestion) and
// metadata used to filter the search by product: product_scope = 'all' or 'motor_comprehensive'.
const text = $input.all().map((i) => i.json.text || '').join('\n')
  .replace(/ClaimShield Mutual - fictional policy wording MW-2026\.1\s*Page \d+/g, '\n');
// Split only on headings ("Part B - ...", "Clause 2.1 - ..."), never on references such as "(Part B)".
const pieces = text.split(/(?=\b(?:Part [A-Z] - |Clause \d+\.\d+ - ))/);
const TITLES = {};
let part = '', scope = 'all';
const out = [];
for (const raw of pieces) {
  const lines = raw.trim().split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) continue;
  const p = lines[0].match(/^Part ([A-Z]) - /);
  if (p) {   // the heading may wrap over two lines: use the whole piece
    part = lines.join(' ').replace(/\s+/g, ' ').trim();
    scope = /motor_comprehensive only/i.test(part) ? 'motor_comprehensive' : 'all';
    continue;
  }
  const c = lines[0].match(/^Clause (\d+\.\d+) - (.*)$/);
  if (!c) continue;
  let title = c[2].trim();
  let body = lines.slice(1).join(' ').replace(/\s+/g, ' ').trim();
  if (!body) {   // heading and text on one line: the title ends where the first sentence starts
    const m = title.match(/^(.{3,80}?)\s+((?:The|There|This|Cover|For|If|Damage|Parts|Painting|Towing|Bodily|Tyres|Any)\b.*)$/);
    if (m) { title = m[1]; body = m[2]; }
  }
  const clause_id = `C-${c[1]}`;
  if (TITLES[clause_id]) continue;
  TITLES[clause_id] = title;
  const applies = scope === 'all' ? 'all motor products' : 'motor_comprehensive only';
  out.push({
    json: {
      pageContent: `[ClaimShield Motor Policy | ${part} | ${clause_id} ${title} | applies to: ${applies}] ${body}`,
      metadata: { clause_id, title, part, product_scope: scope, source: 'Motor-Policy-Wording.pdf' },
    },
  });
}
if (!out.length) throw new Error('No clause found in the policy text: check the PDF');
return out;
