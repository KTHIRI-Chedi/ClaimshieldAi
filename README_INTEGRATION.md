# ClaimShield AI – integrated system (setup and test)

One main workflow (**00_ClaimShield_Orchestrator**) calls the agents as sub-workflows, as in the Solution Design (§4.1):

```
Claim Form / Claim API ──► Prepare Claim ──► Photo checks (EXIF date, reused photo)
   ──► Validate (05, stage validate: fields, policy, dates) ──► invalid → REJECTED (no AI call)
   ──► 03 Visual Inspection ──► 04 Invoice Parser ──► 02 Policy RAG
   ──► 05 Fraud Risk & Decision (stage decide) ──► route: auto_approve | human_review | fraud_investigation
   ──► audit log + photo register + result page + mock payment / Slack review / Slack fraud alert
```

| File | Workflow | From |
|---|---|---|
| 00_ClaimShield_Orchestrator.json | main flow (form + API) | new |
| 01_Policy_Ingestion_Motor.json | indexes the policy wording in Qdrant (run once) | Chedi's ingestion |
| 02_Policy_RAG_Agent.json | coverage check citing clauses | Chedi's RAG agent |
| 03_Visual_Inspection_Agent.json | photo analysis (Gemini) | visual agent |
| 04_Invoice_Parser_Agent.json | invoice reading + arithmetic | Fedi + Omar (unchanged) |
| 05_Validation_Fraud_Decision_Agent.json | validation + risk score + route | Bahaeddine |

Teammates' original files are not modified. Every change made in these copies is listed in **INTEGRATION_CHANGES.md** (useful for the report).

---

## Setup (about 15 minutes, once)

The data files are already in `data/claimshield/` (policies, claim history, motor policy wording PDF).

### 1. Import the 6 workflows (keeps their IDs, so the orchestrator finds its sub-workflows)
In PowerShell, from the `ClaimshieldAi` folder, with Docker running:
```
docker cp integration\workflows claimshield_n8n:/tmp/cs_workflows
docker exec claimshield_n8n n8n import:workflow --separate --input=/tmp/cs_workflows
docker restart claimshield_n8n
```
You should see 6 new workflows (00 to 05) in n8n.

### 2. Credentials (n8n → Overview → Credentials → Create)
1. **Google Gemini(PaLM) API**: paste your Gemini key → Save. Then select it in 3 nodes (open the node, choose the credential, Save the workflow):
   - 03_Visual_Inspection_Agent → **Analyze an image**
   - 02_Policy_RAG_Agent → **Google Gemini Chat Model**
   - 05_Validation_Fraud_Decision_Agent → **Google Gemini Chat Model**
2. **Header Auth** named `ClaimShield API key`: Name `X-API-Key`, Value = a long random string. Select it in 00_ClaimShield_Orchestrator → **Claim API**. (Only the API needs it; the form works without.)
3. NVIDIA_NIM_Free, Local_Qdrant and LlamaParse API already exist on your machine and are already selected.
4. Slack (optional, later): see "Slack" below.

### 3. Index the motor policy (once)
Open **01_Policy_Ingestion_Motor** → **Execute workflow**. The Qdrant node should show **30 items** (30 clauses).
Before running it again (e.g. after changing the document), delete the collection `motor_policy_clauses` in the Qdrant dashboard (http://localhost:6333/dashboard) to avoid duplicates.

### 4. Publish
Publish **02, 03, 04, 05** first (sub-workflows are only callable when published), then **00_ClaimShield_Orchestrator**.

---

## Demo: submit a claim with the form
Open 00_ClaimShield_Orchestrator → **Claim Form** node → copy the **Production URL** → open it in the browser.
After submitting, the result page shows the customer message and the internal summary (route, risk score, warning signs, coverage with clause IDs, processing time).
Every claim is appended to `data/claimshield/decisions_log.jsonl` (audit trail) and its photo fingerprints to `data/claimshield/photo_register.json`.

### Test claims (photos in `integration/test_claims/`, invoices in `data/`) – run them in this order
| # | Policy | Incident date | Amount (TND) | Description | Photo | Invoice | Expected |
|---|---|---|---|---|---|---|---|
| T1 | POL-1001 | 2026-09-10 | 1404.2 | Front collision at a roundabout: front bumper and left headlight damaged. | T1_T3_front_crash.jpg | invoices/INV-001.pdf | auto_approve (payout 1104.2 after the 300 deductible) |
| T2 | POL-1005 | 2026-10-02 | 1602.037 | Choc avant contre un poteau : pare-choc avant, calandre et phare avant gauche endommagés. | T2_front_crash_white.jpg | eval_invoices/c04.pdf | FREQUENT_CLAIMS +10 (3 claims in 12 months), French photos vs French invoice |
| T3 | POL-1001 | 2026-09-10 | 1404.2 | Front collision in a parking lot: front bumper and left headlight. | T1_T3_front_crash.jpg (same as T1) | invoices/INV-001.pdf | fraud_investigation (PHOTO_REUSED +40) |
| T4 | POL-1004 | 2026-10-01 | 800 | Scratched door. | T4_any_photo.jpg | eval_invoices/c02.pdf | rejected: policy cancelled, no AI call |
| T5 | POL-1001 | 2026-10-03 | 1969.45 | Rear-ended at a red light, only the rear bumper was hit. | T5_side_damage.jpg | eval_invoices/c09.pdf | fraud_investigation (damage mismatch + invoice arithmetic + invoiced parts not visible) |
| T6 | POL-1003 | 2026-05-10 | 916.3 | A stone hit the windscreen on the highway. | T6_front_windscreen.jpg | eval_invoices/c08.pdf | human_review: coverage EXCLUDED (third-party policy, clause C-1.1) |
| T7 | POL-1001 | 2026-10-02 | 390.023 | Left mirror broken by a passing truck. | T7_dated_2026-09-01.jpg | eval_invoices/c02.pdf | PHOTO_BEFORE_INCIDENT +15 (EXIF date 2026-09-01) |
| T8 | POL-1001 | 2026-10-04 | 916.3 | Hail storm yesterday cracked the windscreen and damaged the bonnet. | T8_rusty_bonnet.jpg | eval_invoices/c08.pdf | PRE_EXISTING_DAMAGE (rust, flaking paint) |

These results were checked end to end with simulated AI answers. With the real models the visual agent judges the photos itself, so T5, T7 and T8 can collect extra or different signs; the route logic stays the same.
Note: the test photos are stock images with watermarks; the visual agent may report them in `suspicious_image_flags`. Use your own photos for the final demo video.
To restart the tests from zero, delete `data/claimshield/photo_register.json` and `decisions_log.jsonl`.

### API (for the report / Postman)
```
POST http://localhost:5678/webhook/claimshield/claims
Header  X-API-Key: <your value>
Body    multipart/form-data: claim_id (optional), policy_id, incident_date, incident_location, description,
        claimed_amount, one field per photo (JPG/PNG), one invoice file (PDF, or a name containing "invoice")
→ 202 Accepted; the decision is written to the audit log.
```

### Slack (optional)
Create a Slack app with a bot token (scopes `chat:write`, `channels:read`), add it to a channel `claims-review`, create the **Slack** credential in n8n, select it in **Ask Adjuster on Slack** and **Fraud Alert on Slack**, then set `slack_enabled: true` in **Prepare Claim** (settings at the top). Human-review claims then wait for Approve / Reject on Slack; the answer is added to the audit log.

---

## Sources
`source/` holds the generator (`build_integration.py` + `js/`) used to produce these workflows and the policy wording (`policy/`). Rebuild: `python source/build_integration.py` (needs the teammates' original JSON files in `source/src`).
