// Search query = accident description + damaged / invoiced parts; the product filters the clauses.
const j = $input.first().json;
const claim = j.claim || {};
const product = String(j.policy?.product || j.product_id || 'motor_comprehensive');
const seen = j.visual && !j.visual.error ? (j.visual.damaged_parts || []) : [];
const invoiced = j.invoice && !j.invoice.error
  ? (j.invoice.line_items || []).filter((l) => l.type === 'part').map((l) => l.part) : [];
const parts = [...new Set([...seen, ...invoiced].map(String))];
// the product is part of the query so the clause defining what this product covers is retrieved too
const productText = product === 'motor_third_party'
  ? 'Product motor_third_party: liability to third parties only, damage to the insured vehicle'
  : `Product ${product}: damage to the insured vehicle`;
const query = [productText, claim.description, parts.length ? `Damaged parts: ${parts.join(', ')}` : '', 'cover, exclusions and conditions']
  .filter(Boolean).join('. ').slice(0, 1200);
return [{ json: {
  claim_id: claim.claim_id, product, query, parts, description: String(claim.description || ''),
  pre_existing: j.visual?.pre_existing_damage_signs === true,
} }];
