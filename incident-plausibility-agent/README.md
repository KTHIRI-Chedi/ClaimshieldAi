# Incident Plausibility Agent (+ fine-tuned reconstruction model)

Walaeddine's part of ClaimShield AI. A new agent that checks whether the claimant's **story** could have happened where and when they say, and whether the **invoice fits that story**. It returns a score in a shared format the decision agent can add to the claim's risk score.

Everything is in this folder; nothing else in the repo is changed.

| Folder / file | What it is |
|---|---|
| `incident-plausibility/incident_plausibility_agent_local.json` | **The n8n workflow, local version**: both AI steps on **Ollama** (fine-tuned `claimshield-recon` + base `qwen2.5:3b`). No API, no key, no credential |
| `incident-plausibility/incident_plausibility_agent.json` | **The n8n workflow, API version**: Groq by default (or Gemini/OpenRouter/OpenAI), needs a key. Use it if the laptop is too slow for local models |
| `incident-plausibility/README.md` | How the agent works, its warning signs, tests, known limits |
| `incident-plausibility/PROMPTS.md` | Versioned prompt library: techniques, failure cases, before/after (for the report) |
| `incident-plausibility/explainer.html` | One-page visual explanation, for the demo |
| `incident-plausibility/dev/finetune/` | **Fine-tuning**: dataset generator, Colab QLoRA notebook (Qwen2.5-3B), results of the training run, Ollama Modelfile |
| `incident-plausibility/dev/eval/` | Labeled test claims and the evaluation runner (prompt versions, base vs fine-tuned) |
| `contracts/` | **Shared agent result format** + example Code nodes (merge in the decision agent, failure fallback) |
| `claim-form/` | Optional claim form with a **map pin** (exact incident coordinates) and GPS button |
| `SETUP.md` | Full step-by-step setup and linking guide |
| `model/` | Put `claimshield-recon-Q4_K_M.gguf` here (not in git: ~2 GB, on Google Drive) |

## Status
| Part | Status |
|---|---|
| Agent workflow, Groq (free API) | Ran in n8n with real Groq answers on the sample claim: 20 points, 2 warning signs (as expected) |
| Guardrails (quote checks, schema repair, rate limits, map-server fallback) | 9 automated tests pass (`node incident-plausibility/dev/tests.js`) |
| Fine-tuning (QLoRA, Qwen2.5-3B) | Trained on Colab: synthetic test set 0 → 100% impact-zone accuracy, 80/80 valid JSON (results in `dev/finetune/results/`) |
| Fine-tuned model inside n8n (Ollama) | **Not tested yet**: to do on the integration laptop |
| Link into `00_ClaimShield_Orchestrator` | **To do** (steps below) |

## Integrating into this repo's `integration/` setup

**1. Import the agent.** Choose one of the two versions. The local one uses the fine-tuned model and needs Ollama running with `claimshield-recon` and `qwen2.5:3b` (SETUP.md part A3).
```
docker cp incident-plausibility-agent\incident-plausibility\incident_plausibility_agent_local.json claimshield_n8n:/tmp/06_incident_plausibility.json
docker exec claimshield_n8n n8n import:workflow --input=/tmp/06_incident_plausibility.json
```
Or in the n8n UI: **Import from File**. The local version needs **no credential**: just put your email in **Geocode incident** and run it.

On a CPU the local version takes a few minutes per claim. Two settings in **LLM settings** speed it up:
- `RECONSTRUCTION_SAMPLES = 1` for quick tests.
- `extraction: 'groq'`: fact extraction moves to Groq, which is faster and better; the reconstruction stays on the fine-tuned model. This needs a Header Auth credential on **Extract facts (LLM)**.

**2. API version only.** The team already has a **Gemini** key, and the agent can use it:
- In **LLM settings**, set `PROVIDER = { extraction: 'gemini', reconstruction: 'gemini' }`.
- Create a **Header Auth** credential with Name `Authorization` and Value `Bearer <gemini key>`, and select it in the two LLM nodes.

Groq (free) is the default. The fine-tuned model runs with `reconstruction: 'ollama'` and `RECONSTRUCTION_PROMPT = 'ft1'` (SETUP.md part A3).

**3. Call it from `00_ClaimShield_Orchestrator`**, after the Invoice Parser (`04`) and before the decision (`05`):
- **Edit Fields** → `{ claim: {...}, invoice: { line_items: [{ part }] } }`. The claim needs `claim_id`, `incident_datetime`, `description`, and ideally `incident_lat` / `incident_lon`.
- **Execute Workflow** → this agent, with **Wait for completion** on and **On Error: continue (error output)** → `contracts/failed_result_example.js`.
- Pass its output to **05 Fraud Risk & Decision**: add `score` to the rule score (capped at 60 as in the design), and add `warning_signs[]` to the decision record. `contracts/decision_merge_example.js` shows the logic.

**4. Part names.** The agent compares invoiced parts with the reconstructed accident using shared names (`rear_bumper`, `radiator`…), listed in `incident-plausibility/dev/prompts/vocabulary.js`. Map the Invoice Parser's part names to these when building the input. The `integration/source/js/rule_parts.js` file in this repo may already do part of it.

**5. Possible overlap with `05`.** `05` already scores "damage inconsistent with description" (from the photos) and "invoiced part not visible". This agent's signs come from different evidence: map, weather, the story's own logic, and the invoice vs the reconstructed accident. If the same part is flagged by both, count it once.

## Regenerating files
- **Workflow:** `python incident-plausibility/dev/build.py incident-plausibility/incident_plausibility_agent.json`
- **Training data:** `node incident-plausibility/dev/finetune/generate_dataset.js`. It's not in git, and is regenerated identically (seed 42).
- **Notebook:** `python incident-plausibility/dev/finetune/build_notebook.py`
