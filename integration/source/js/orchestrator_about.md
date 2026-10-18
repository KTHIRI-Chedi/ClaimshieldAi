## ClaimShield AI - Orchestrator
**Claim Form** (demo) or **Claim API** (POST /webhook/claimshield/claims, header auth) ->
1. **Prepare Claim**: one claim format; photos -> photo_0.., invoice -> invoice. *Settings at the top.*
2. **Photo Checks / Register Check**: EXIF date of each photo, fingerprint vs earlier claims (reused photo).
3. **Validate Claim** (decision agent, stage validate): fields, policy, coverage dates. Invalid -> rejected, no AI call.
4. **Visual Inspection** -> **Invoice Parser** -> **Policy RAG** (sub-workflows; a failed agent never blocks the claim).
5. **Fraud Risk & Decision** (stage decide): rule score (max 60) + LLM (max 40) -> auto_approve / human_review / fraud_investigation.
6. Outputs: audit log (data/claimshield/decisions_log.jsonl), photo register, result page, mock payment, Slack review / alert.
