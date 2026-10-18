// Sample input to test this agent alone (the orchestrator sends the same shape).
return [{ json: {
  claim: { claim_id: 'CLM-TEST-RAG', description: 'Rear-ended at a red light. Rear bumper and boot lid damaged.' },
  policy: { policy_id: 'POL-1001', product: 'motor_comprehensive' },
  visual: { damaged_parts: ['pare-choc arriere', 'coffre'], pre_existing_damage_signs: false },
  invoice: { line_items: [ { part: 'Rear bumper', type: 'part' }, { part: 'Boot lid', type: 'part' }, { part: 'Labour', type: 'labor' } ] },
} }];
