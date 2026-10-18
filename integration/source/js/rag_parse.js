// Parse the model's answer and check it against what was retrieved (grounding): a clause that was not
// retrieved cannot be cited, and COVERED / EXCLUDED without any retrieved clause becomes REQUIRES_REVIEW.
const ctx = $('Build Context').first().json;
const raw = String($json.text ?? $json.output ?? '');
const STATUSES = ['COVERED', 'EXCLUDED', 'REQUIRES_REVIEW'];
const cleaned = raw.replace(/<think>[\s\S]*?<\/think>/gi, '').replace(/```json|```/g, '').trim();
let p = null;
for (const c of [cleaned, ...(cleaned.match(/\{[\s\S]*\}/g) || [])]) {
  try { const o = JSON.parse(c); if (o && o.coverage_status) { p = o; break; } } catch (e) { /* next */ }
}
const notes = [];
if (!p) notes.push($json.error ? `LLM error: ${String($json.error).slice(0, 200)}` : 'answer was not valid JSON');
p = p || {};
let status = String(p.coverage_status || '').toUpperCase().trim();
if (!STATUSES.includes(status)) status = 'REQUIRES_REVIEW';
const retrieved = new Set(ctx.retrieved_ids || []);
const cited = [...new Set((p.cited_clauses || []).map((s) => (String(s).match(/\d+\.\d+/) || [])[0]).filter(Boolean).map((n) => `C-${n}`))];
const grounded = cited.filter((c) => retrieved.has(c));
const ungrounded = cited.filter((c) => !retrieved.has(c));
if (ungrounded.length) notes.push(`cited clauses that were not retrieved were removed: ${ungrounded.join(', ')}`);
if (!retrieved.size) { status = 'REQUIRES_REVIEW'; notes.push('no policy clause retrieved'); }
else if (status !== 'REQUIRES_REVIEW' && !grounded.length) { status = 'REQUIRES_REVIEW'; notes.push('no retrieved clause supports the answer'); }
return [{ json: {
  coverage_status: status,
  cited_clauses: grounded,
  reasoning: String(p.reasoning || ''),
  flagged_exclusions: Array.isArray(p.flagged_exclusions) ? p.flagged_exclusions.map(String) : [],
  product: ctx.product,
  retrieved_clauses: ctx.clauses.map((c) => ({ clause_id: c.clause_id, title: c.title, score: c.score })),
  grounding_ok: ungrounded.length === 0,
  notes,
} }];
