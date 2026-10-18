// The retrieved clauses, de-duplicated, become the only context the model may use.
const q = $('Build Query').first().json;
const clauses = [];
for (const d of $input.all().map((i) => i.json).filter((x) => x.document)) {
  const m = d.document.metadata || {};
  const id = m.clause_id || (String(d.document.pageContent).match(/C-\d+\.\d+/) || [])[0];
  if (!id || clauses.some((c) => c.clause_id === id)) continue;
  clauses.push({ clause_id: id, title: m.title || '', product_scope: m.product_scope || 'all',
                 score: Math.round((d.score ?? 0) * 1000) / 1000, text: d.document.pageContent });
}
return [{ json: {
  ...q, clauses, retrieved_ids: clauses.map((c) => c.clause_id),
  context: clauses.map((c) => `[${c.clause_id}] ${c.text}`).join('\n\n'),
} }];
