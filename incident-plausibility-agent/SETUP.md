# ClaimShield AI: setup and linking guide

This guide sets up the claim form, the Incident Plausibility agent (with its fine-tuned model) and connects them to the rest of the ClaimShield workflows.

## How the pieces connect

```
 Claimant's phone/browser
        │  GET /webhook/claim-form  (map pin, photos, invoice PDF)
        ▼
 ┌───────────────────────────┐
 │ Claim Intake Form (n8n)   │  validates → claim ID (HTTP 202) → "Run orchestrator"
 └────────────┬──────────────┘
              ▼  { claim } + files photo_1..n, invoice
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ Orchestrator (your team)                                                  │
 │   policy check ─┬─ Visual Inspection ──────────────────────────┐          │
 │                 ├─ Invoice Parser ─► Incident Plausibility ────┼─► Merge ─► Fraud Risk & Decision ─► route
 │                 └─ Policy RAG ─────────────────────────────────┘          │
 └───────────────────────────────────────────────────────────────────────────┘
                                   │ reconstruction step
                                   ▼
                     Groq (free API)  or  Ollama + fine-tuned Qwen2.5-3B (your PC)
```

Every agent returns the **same result format** (`contracts/agent_result.schema.json`). The decision agent merges them the same way, whichever agent they come from.

| Folder | What's in it |
|---|---|
| `claim-form/` | The claim page and intake workflow |
| `incident-plausibility/` | The agent workflow, prompts, tests, evaluation, fine-tuning |
| `contracts/` | The shared result format and example Code nodes for the orchestrator |
| `model/` | Put the fine-tuned model (`.gguf`) and its `Modelfile` here |

---

## Part A: One-time setup

### A1. n8n container settings
You already run n8n in Docker. The claim form needs two environment variables, and one more is optional. Add them where you start the container.

**With docker compose**, under `environment:`:
```yaml
      - N8N_PAYLOAD_SIZE_MAX=32                         # claims carry photos + a PDF
      - WEBHOOK_URL=http://localhost:5678/              # your public URL (or HTTPS tunnel for a phone demo)
      - N8N_INSECURE_DISABLE_WEBHOOK_IFRAME_SANDBOX=true   # optional: lets the form use the phone's GPS
```
then run `docker compose up -d`.

**With `docker run`**, recreate the container with the **same volume** so your workflows and credentials are kept: add `-e N8N_PAYLOAD_SIZE_MAX=32 -e WEBHOOK_URL=http://localhost:5678/` to your command. Keep your `-v ...:/home/node/.n8n` exactly as before.

If you skip this, the form still works, but uploads over 16 MB fail and the GPS button may be blocked.

### A2. Free AI key (Groq)
1. Go to **console.groq.com → API Keys → Create API Key**, and copy the key (`gsk_...`).
2. In n8n: **Credentials → Add credential → Header Auth**.
   - **Name:** `Authorization`
   - **Value:** `Bearer gsk_your_key` (with "Bearer" and a space)
   - Save it as **`Groq API key`**.

### A3. Fine-tuned model on your PC (optional, for the fine-tuning part of the project)
1. Download `claimshield-recon-Q4_K_M.gguf` from your Google Drive. Put it with `Modelfile` in `incident-plausibility-agent\model\`.
2. Install **Ollama** from ollama.com/download (Windows).
3. In PowerShell:
   ```powershell
   cd "<path to the repo>\ClaimshieldAi\incident-plausibility-agent\model"
   ollama create claimshield-recon -f Modelfile
   ollama pull qwen2.5:3b
   setx OLLAMA_HOST 0.0.0.0
   ```
   Then quit Ollama from the tray icon and start it again, so n8n in Docker can reach it.
4. Check: `ollama list` shows `claimshield-recon` and `qwen2.5:3b`.

---

## Part B: Import and configure the workflows

### B1. Incident Plausibility agent
1. **Workflows → Import from File →** `incident-plausibility/incident_plausibility_agent.json` (24 nodes). If an older version exists, delete it first.
2. **Extract facts (LLM)** and **Reconstruct incident x3 (LLM)**: in **Credential for Header Auth**, select **Groq API key**. Change nothing else in these nodes, and **don't import cURL** into them.
3. **Geocode incident** → Headers → User-Agent: replace `(replace with your team contact)` with your email.
4. **LLM settings**: pick where the reconstruction runs.

   | Use | Settings |
   |---|---|
   | Everything on Groq (fastest to set up) | `reconstruction: 'groq'`, `RECONSTRUCTION_PROMPT = 'v2'` |
   | **Fine-tuned model** on your PC | `reconstruction: 'ollama'`, `RECONSTRUCTION_PROMPT = 'ft1'` |

   Keep `extraction: 'groq'`. On a CPU, set `RECONSTRUCTION_SAMPLES = 1` for quick tests and `3` for the real runs.
5. **Save**, then click **Test workflow**. It runs the built-in sample claim (about 2 minutes on Groq's free tier). The last node, **Plausibility score (output)**, shows the result (see Part D).
6. Note the workflow's name. The orchestrator selects it by name.

### B2. Claim form
1. **Import →** `claim-form/claim_form_workflow.json`.
2. **Nominatim** node → User-Agent: put your email.
3. **Activate** the workflow (toggle at the top right).
4. Open `http://localhost:5678/webhook/claim-form` and check that the map loads.
5. **Run orchestrator** node: select your **orchestrator** workflow, then **enable** the node. It's disabled at first so the form can be tested alone.

---

## Part C: Link the agent into the orchestrator

In the orchestrator workflow (your team's), after the **Invoice Parser**:

**C1. Edit Fields (Set) node "Plausibility input"**: Mode **JSON**, with this value (adapt the two names in `$(...)` to your node names):
```
{{ JSON.stringify({
  claim: $('Create claim').item.json.claim,
  invoice: { line_items: $json.line_items }
}) }}
```
- `claim` must contain `claim_id`, `incident_datetime`, `description`, and ideally `incident_lat` / `incident_lon` (the claim form provides all of them).
- `line_items[].part` must use the shared part names (`rear_bumper`, `radiator`…), listed in `incident-plausibility/dev/prompts/vocabulary.js`. Unknown names are skipped, never flagged.

**C2. Execute Workflow node "Incident Plausibility"**
- **Source:** Database. **Workflow:** select *ClaimShield - Incident Plausibility Agent*.
- **Mode:** Run once with all items. **Wait for sub-workflow completion:** on.
- **Settings → On Error:** *Continue (using error output)*.

**C3. Error output → Code node "Plausibility failed"**: paste `contracts/failed_result_example.js`, adapting `$('Create claim')` to your node name. A failure then becomes a `status: "failed"` result, so the decision agent sends the claim to a human instead of treating it as "no risk".

**C4. Merge**: connect the normal output **and** the "Plausibility failed" output, along with the other agents' outputs, into one **Merge** node in **Append** mode.

**C5. Decision agent**: a Code node after the Merge, based on `contracts/decision_merge_example.js`. It collects all warning signs, caps the rule score at 60 as in the design, counts independent agents, and flags failed agents.

**For the other agents:** ask each owner to end their workflow with a node that returns the same format (`contracts/agent_result.schema.json`): `agent`, `claim_id`, `status`, `score`, `score_max`, `warning_signs[]`, `summary`, `details`. That's what makes them all "plug-in" for the decision agent.

---

## Part D: What the agent returns

The last node, **Plausibility score (output)**, returns one item:

```json
{
  "agent": "incident_plausibility",
  "schema_version": "1.0",
  "claim_id": "CLM-2026-JZ6ON8JS",
  "status": "ok",
  "score": 20,
  "score_max": 75,
  "score_normalized": 0.267,
  "weighted_score": 15.5,
  "agent_risk_level": "medium",
  "warning_signs": [
    { "code": "WEATHER_OR_LIGHT_CONTRADICTION", "points": 15, "confidence": "medium",
      "evidence": "Claimant reports rain, but recorded 0 mm precipitation and \"cloudy\" around the incident time." },
    { "code": "INVOICE_PART_IMPLAUSIBLE", "points": 5, "confidence": "high",
      "evidence": "Invoice includes radiator, which a rear_end_struck with rear impact would not damage." }
  ],
  "summary": "2 warning signs, 20 points: weather or light contradiction; invoice part implausible.",
  "details": { "reconstruction": {}, "facts": {}, "context": {}, "invoice_check": {}, "notes": [] }
}
```

| Field | How the decision agent uses it |
|---|---|
| `score` | Points added to the claim's **rule score** (the design caps the rule score at 60) |
| `score_max`, `score_normalized` | Compare agents on one scale (0–1) |
| `weighted_score` | The same points weighted by confidence (high 1.0 · medium 0.7 · low 0.4), to discount weak signals |
| `warning_signs[]` | Count independent signs (the design needs ≥2 for an investigation), and show the evidence to the adjuster |
| `status` | `partial`: some checks were skipped, so the score covers the rest. `failed`: send to a human |
| `agent_risk_level` | This agent's own reading (low < 10 ≤ medium < 25 ≤ high). The final route is decided by the decision agent only |
| `summary` | One line for the Slack review message. **Never shown to the customer** |

---

## Part E: Test everything end to end
1. Make sure the claim form and orchestrator workflows are active, and Ollama is running if you use it.
2. Open `http://localhost:5678/webhook/claim-form` and file a test claim:
   - **story:** *"I was stopped at the traffic light when a car hit the back of my car. It was raining heavily."*
   - **date:** a past date, around 18:40
   - **location:** pin on the map
   - **files:** 1–3 photos and any PDF as the invoice
3. You get a claim number. In n8n, open **Executions**: the form, the orchestrator and the Incident Plausibility execution should all appear.
4. Open the Incident Plausibility execution → **Plausibility score (output)** to see the score and evidence.

## Part F: Evaluation for the report (optional, on your PC)
From the `incident-plausibility` folder (Node 18+):
```powershell
$env:LLM_API_KEY="gsk_your_key"
node dev/eval/run_eval.js --provider groq
node dev/eval/run_eval.js --ext-provider groq --configs "v3+ft1@ollama:qwen2.5:3b,v3+v2@ollama:qwen2.5:3b,v3+ft1@ollama:claimshield-recon,v3+v2@groq"
```
- The first command compares the prompt versions.
- The second compares base vs fine-tuned 3B vs the 120B reference.
- Results go to `dev/eval/results/`.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `401` / "Invalid API Key" on an LLM node | Credential value must be `Bearer <key>` |
| `429` / "too many requests" | Groq's free per-minute limit. Wait 1 minute; or `CALL_INTERVAL_SECONDS = 40` or `RECONSTRUCTION_SAMPLES = 1` in **LLM settings** |
| "The model answered with text instead of JSON…" | An LLM node was edited (e.g. cURL import). Re-import the workflow |
| Road context nodes slow, or `status: partial` with "Map data unavailable" | Public map servers busy; the agent continues without map checks. Run again later |
| "connection refused" to `host.docker.internal:11434` | Ollama not running, or `OLLAMA_HOST` not set (A3) |
| Ollama answers very slowly | Normal on a CPU (20–60 s per answer); use `RECONSTRUCTION_SAMPLES = 1` |
| Form: map doesn't load, or GPS is blocked | Workflow not active; GPS needs HTTPS (tunnel) and the sandbox setting in A1 |
| Orchestrator gets nothing from the agent | Execute Workflow: "Wait for sub-workflow completion" must be on; the agent's last node is **Plausibility score (output)** |
