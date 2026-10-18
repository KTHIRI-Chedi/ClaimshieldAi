// __LLM__
// __GROUNDING__
// Guardrails between the two LLM steps:
// 1. the answer is parsed and forced into the schema (free models do not always follow it);
// 2. every extracted fact must quote the description, and facts with a missing or invented
//    quote are dropped before they can trigger a check.
const n = $('Normalize input').first().json;
const { schema } = $('Build extraction request').first().json;
const raw = LLM.conform(LLM.parse(LLM.contentOf($input.first().json)), schema);
const { facts, dropped, evidence, grounded } = GROUNDING.verifyFacts(raw, n.description);

return [{ json: { facts, evidence, dropped_facts: dropped, grounded } }];
