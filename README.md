# ClaimShield AI

An explainable, multi-agent assistant for private car insurance claims, built on n8n.

A client fills in one page: their details, the date, time and place of the accident (with a map pin), what happened, damage photos and the repair invoice. Four specialist agents check the claim in parallel, a decision stage adds up bounded warning signs, and the claim is routed to **auto-approve**, **human review** or **fraud investigation**. The client gets a clear answer by email; the insurer gets every warning sign, its points and the agent that raised it.

> Final project, Advanced Deep Learning, Esprit 2026–2027.
> Full write-up: [docs/ClaimShield_AI_Final_Project_Report.pdf](docs/ClaimShield_AI_Final_Project_Report.pdf)

## Team

| Member | Role |
|---|---|
| Walaeddine Ghazouani | Team lead, integration, demo |
| Omar Jalled | Multi-agent architect |
| Maha Ben Mehrez | Fraud risk and decision |
| Fedi Mdaini | Multimodal and documentation |
| Chedi Kthiri | RAG engineer |
| Bahaeddine Amara | Prompt engineering and QA |

## How it works

```
Claim page (/webhook/claim, map pop-up)  or  plain form (/form/claimshield)
      |
04 Validation & Fraud Decision Agent  (orchestrator)
      |  required fields, future date, photo fingerprints (SHA-256), photo dates (EXIF)
      |  invalid -> rejected, no AI call
      |
      |-- photos ------> 03 Visual Inspection    Gemini Flash vision, 29 shared part codes
      |-- invoice -----> 03 Invoice Parser        LlamaParse OCR + gpt-oss-20b (NVIDIA NIM), arithmetic check
      |-- story -------> 02 Policy RAG            Qdrant + Nemotron embeddings, Cohere rerank, local gemma2, LLM judge
      |-- date/place --> 05 Incident Plausibility OpenStreetMap + Open-Meteo + local fine-tuned model (claimshield-recon)
      |
      |  fraud score = rule score (max 60) + Gemini adjustment (max 40)
      |  auto-approve < 20 and amount <= 2000 TND | human review 20-49 or over limit | fraud >= 50
      |
      |-- email to the client (never mentions suspected fraud)
      |-- email to the insurer, Airtable record, result page
```

| Workflow file | What it does |
|---|---|
| `01_Document_Ingestion.json` | Splits the policy PDF (500/50 characters), embeds it and stores it in Qdrant `policy_clauses` |
| `02_Policy_RAG_Agent.json` | Finds and cites the policy clauses that apply to the story |
| `03_Visual_Inspection_Agent.json` | Reads the damage photos |
| `03_Invoice_Parser_Agent.json` | OCR and structured extraction of the repair invoice |
| `04_Validation_Fraud_Decision_Agent.json` | Claim page, validation, calls the 4 agents, scores and routes |
| `04b_Agent_Test_Runner.json` | 26 automated tests of the validation and decision logic |
| `05_Incident_Plausibility_Agent.json` | Checks the story against the map and the weather |
| `00_ClaimShield_Orchestrator.json` | Earlier orchestrator, kept for reference (unpublished) |

All workflows are in [`Workflows/`](Workflows/), ready to import into n8n by hand (*Create workflow → ⋯ → Import from file*). `data/integration/workflows/` holds the same files under the names `install.cmd` uses.

## Repository layout

```
Workflows/                  every n8n workflow of the project (import from file)
docker-compose.yml          n8n, Qdrant and the n8n sandbox service
.env.example                the environment variables to fill in (copy to .env)
data/                       mounted in n8n as /data
  Policy-Document.pdf       the motor policy the RAG agent reads
  integration/workflows/    the same workflows for install.cmd, plus the Ollama credential (no secrets)
integration/
  README.md                 the claim scenario and how to run the demo
  install.cmd               imports and publishes the workflows into the running n8n
  update_rag.cmd            re-imports the RAG agent only
  test-scenarios/           6 ready-made claims (photos + invoices) for the demo
  prompt-library/           every prompt, its versions and its failure cases
  rag-eval/                 chunking evaluation (code, queries, results)
model/Modelfile.txt         Ollama definition of the fine-tuned claimshield-recon model
airtable/                   sample Airtable tables (fictitious data)
docs/                       final report
```

## Run it

**You need:** Docker Desktop, [Ollama](https://ollama.com), and free accounts for Google AI Studio (Gemini), NVIDIA NIM, Cohere, Airtable and LlamaParse.

1. **Clone and configure**
   ```
   git clone <this repository>
   cd ClaimshieldAi
   copy .env.example .env
   ```
   Open `.env` and fill in your own values.

2. **Local models**
   ```
   ollama pull gemma2:latest
   ollama pull qwen2.5:3b
   ```
   For the fine-tuned model, put `claimshield-recon-Q4_K_M.gguf` (1.9 GB, shared separately because it is too large for GitHub) in `model/`, then:
   ```
   cd model
   ollama create claimshield-recon -f Modelfile.txt
   ```

3. **Start the stack**
   ```
   docker compose up -d
   ```
   n8n opens at http://localhost:5678.

4. **Add the credentials in n8n** (*Overview → Credentials → Create credential*), using exactly these names so the workflows find them:

   | Name in n8n | Type | Used by |
   |---|---|---|
   | `Google Gemini(PaLM) Api account` | Google Gemini (PaLM) API | visual agent, decision |
   | `NVIDIA_NIM_Free` | OpenAI, base URL `https://integrate.api.nvidia.com/v1` | embeddings, RAG |
   | `nvidia-omar` | OpenAI, base URL `https://integrate.api.nvidia.com/v1` | invoice parser |
   | `Cohere account` | Cohere | reranker |
   | `Local_Qdrant` | Qdrant, URL `http://qdrant:6333` | RAG, ingestion |
   | `Airtable Personal Access Token account` | Airtable Personal Access Token | saving claims |

   The Ollama credential is imported by `install.cmd`.

5. **Import the workflows**
   ```
   integration\install.cmd
   ```

6. **Index the policy:** open *Document Ingestion & Vector Indexing Pipeline* in n8n and click **Execute workflow**.

7. **Try a claim:** open http://localhost:5678/webhook/claim and submit one of the folders in `integration/test-scenarios/`. Each folder name says the expected route.

## Tests

Open **04b_Agent_Test_Runner** in n8n and click **Execute workflow**. It runs 26 tests of the validation rules, the warning signs and the routing thresholds, without calling any model.

## Security

- No key, password or token is stored in this repository. API keys live only in your local `.env` and in n8n's encrypted credential store (`n8n_data/`), and both are ignored by git.
- `n8n_data/` and `qdrant_data/` are never committed: they hold the n8n encryption key, the encrypted credentials and the execution history with client photos.
- If you find a secret in this repository, do not use it: open an issue so it can be revoked.

## Limitations

The weights and thresholds come from the design document and were tested on scenarios, not calibrated on real labelled claims. See section 15 of the report.
