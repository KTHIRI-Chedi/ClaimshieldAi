# Integration changes

Teammates' original workflows are unchanged; these are the changes made in the integration copies (folder `integration/workflows`).

## 05_Validation_Fraud_Decision_Agent (Bahaeddine)
- Policies and claim history read from local CSV files (data/claimshield/*.csv) instead of Airtable: Find Policy / Find Prior Claims replaced by Read + Extract From File nodes, Policy Lookup filters by policy_id.
- Rule Score: French (visual agent) and English (invoices) part names are mapped to one canonical name before the PART_NOT_VISIBLE check; only lines of type 'part' are compared (paint/consumables are 'other').
- Rule Score: invoice status needs_review and invoice warnings are passed as review_flags (0 points).
- Decide Route: review_flags are route reasons, so such a claim goes to human_review instead of auto_approve.
- Gemini credential re-pointed to Fedi's own Gemini key (model unchanged).

## 03_Visual_Inspection_Agent
- Sub-workflow trigger set to 'accept all data' (passthrough) so the photos sent by the orchestrator arrive as binary files together with claim_id, description and incident_date.
- Gemini credential re-pointed to Fedi's own Gemini key (model and prompt unchanged).

## 04_Invoice_Parser_Agent (Fedi + Omar)
- Unchanged (same file as the agent folder, renamed 04 because the visual agent is 03).

## 01_Policy_Ingestion_Motor (from Chedi's 01_Policy_Ingestion)
- Reads the new motor policy wording (data/claimshield/policy/Motor-Policy-Wording.pdf): the original Policy-Document.pdf is an HDFC *life* group policy, unrelated to car damage claims.
- Clause splitter anchored on 'Part X - ' / 'Clause n.m - ' headings (the original regex also split inside sentences such as '(Part B)'), page footers removed.
- Each chunk keeps Chedi's structural header ([Product | Clause]) and gets metadata clause_id, title, part and product_scope ('all' or 'motor_comprehensive') so retrieval can be filtered by the customer's product.
- New Qdrant collection 'motor_policy_clauses' (same NVIDIA embedding model nvidia/nemotron-3-embed-1b).

## 02_Policy_RAG_Agent (from Chedi's 02_Policy_RAG_Agent)
- Callable by the orchestrator (When Executed by Another Workflow) with { claim, policy, visual, invoice }; manual test data kept.
- Retrieve-then-generate instead of an AI Agent with a search tool: the Qdrant node retrieves the 8 closest clauses, filtered by the customer's product (design §4.4), and one LLM call decides coverage. Fewer calls, deterministic retrieval, easier to evaluate.
- Same output contract as Chedi's agent (coverage_status, cited_clauses, reasoning, flagged_exclusions) + retrieved_clauses; the JSON text is parsed and checked (only clause IDs that were retrieved can be cited).
- Chat model: Gemini (the nemotron-3.5 model timed out on the free NVIDIA tier); embeddings unchanged (nvidia/nemotron-3-embed-1b).

## 00_ClaimShield_Orchestrator (new)
- New main workflow (design §4.1/4.3): form or authenticated webhook intake -> photo checks -> validation -> visual, invoice and policy agents -> decision -> route -> actions and audit log.
- Photo checks not done by any agent: EXIF date of each photo (PHOTO_BEFORE_INCIDENT rule) and a file fingerprint compared with all earlier claims (PHOTO_REUSED rule), register in data/claimshield/photo_register.json.
- Every claim (accepted or rejected) is appended to data/claimshield/decisions_log.jsonl (audit trail, design §4.8).
- Actions: auto_approve -> mock payment request; human_review -> Slack approve/reject (send and wait); fraud_investigation -> Slack alert. Slack is off until settings.slack_enabled is true in Prepare Claim.
- The result page separates the customer message (never mentions fraud, design §4.8) from the internal summary.
