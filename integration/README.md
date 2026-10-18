# ClaimShield AI: the claim scenario, and how to run the demo

## 1. The scenario

```
Claim page  (http://localhost:5678/webhook/claim, with a map pop-up to pin the exact place)
  or the plain form (http://localhost:5678/form/claimshield, no map)
  your details: name, email, phone (optional)
  the accident: date, hour, street, city, postal code (optional), country, what happened
  documents:    photos (1 to 8), invoice PDF
      |
04 Validation & Fraud Decision Agent        <- the form is inside this workflow
      |  validation: required fields, photo fingerprints (reused?) and photo dates (EXIF)
      |  invalid -> Rejected (no AI call)
      |
      |-- photos ------> 03 Visual Inspection Agent  -> damaged parts + description of the accident
      |-- invoice -----> 03 Invoice Parser (OCR)     -> summary + key information of the invoice
      |-- description -> 02 Policy RAG Agent         -> the policy clauses for this accident (local gemma2)
      |-- date, time, address, description (form)
      |                -> 05 Incident Plausibility    -> does the story fit the map and the weather
      |                   Agent (local Ollama)           at that place and time?
      |
      |  the 4 outputs come back to 04 ("All Agents Answered")
      |  fraud score = rule score (design 4.6, max 60) + Gemini adjustment (max 40)
      |  route: auto-approve < 20 | human review 20-49 or amount above 2000 TND
      |         | fraud investigation >= 50 with 2 signs, or a reused photo
      |
      |-- email to the client   (decision + why; if not fraud: what the policy says for the case)
      |-- email to the insurer  (route, score, warning signs, each agent's output)
      |-- saved in Airtable (Claims) and shown on the result page
```

There is no policy number any more. The client does not know it, so the RAG agent finds the clauses that apply from the description alone. Airtable is now only used to save the claims.

## 2. What changed in this version

### 04_Validation_Fraud_Decision_Agent
| Change | Details |
|---|---|
| **Policy number removed** | The field is gone from the form, and so are the nodes that used it (Find Policy, Find Prior Claims, Policy Lookup). **Eligibility Check** is now **Claim Checks**: a claim is valid when the required fields are there (date, description, photos, and the amount only if there is no invoice) and the photos pass their checks. |
| **Two rules removed** | NEW_POLICY and FREQUENT_CLAIMS needed a policy, so they are no longer scored. Every other rule from table 4.6 is unchanged. |
| **New form fields** | Full name, email, phone (optional), hour, street, city, postal code (optional) and country. The claim keeps the full address as `incident_location` and sends it to the plausibility agent. |
| **New form style** | A clean card on a navy band, with the Inter font, three sections (Your details, The accident, Documents) and a "Submit my claim" button. The CSS is in the Claim Form node, under Options → Custom CSS. |
| **Plausibility agent wired in** | **Send Accident Details** takes the date, time, street, city, postal code, country and description from the form and calls **Incident Plausibility Agent**, in parallel with the other agents. Its result is an input of **All Agents Answered**. It no longer receives anything from the invoice: the invoice is compared with the photos by the score (PART_NOT_VISIBLE). |
| **Plausibility in the score** | When the agent finds warning signs, INCIDENT_IMPLAUSIBLE adds its weighted score, capped at 20. If the agent fails, it counts as a missing agent and the claim goes to human review. The Gemini prompt now has an INCIDENT PLAUSIBILITY RESULT section. |
| **Parts compared by code** | After the OCR agent, **Map Invoice Parts** turns the invoice lines ("Pare-choc AR", "Feu arrière gauche"…) into the shared part codes (`rear_bumper`, `taillight_left`…). PART_NOT_VISIBLE compares them with the codes the visual agent saw. |
| **Auto-approval limit** | 2000 TND, set at the top of **Decide Route** (`CONFIG.auto_approval_limit`). If the invoice total could not be read, the claim goes to human review. |
| **New emails and result page** | Both emails and the result page have a modern layout: header, decision badge, score, sections. The client still never reads the word fraud (design 4.8). |

### Claim page with a map (new)
The n8n form blocks scripts, so a map cannot run inside it. Workflow 04 therefore also serves its own claim page at **http://localhost:5678/webhook/claim** (nodes **Claim Page (with map)** → **Send Claim Page**). It has the same fields and look, plus an **Open the map** button:
- A pop-up opens with a map and a search box. Search the street, or click on the map, then drag the pin to the exact spot and click **Use this location**.
- The street, city, postal code and country fill in by themselves (they can still be edited).
- The page sends the claim to the same **Claim Form**, with the pin in two hidden fields (`incident_lat`, `incident_lon`), and then shows the same result page.
- The plausibility agent uses the pin instead of searching the address, so the road and weather checks always run. The insurer email has a "pinned on the map" link.
- The map needs internet in the browser (map tiles and the address search come from OpenStreetMap). Without a pin, the address search with fallbacks is used, as before. The old form (/form/claimshield) still works.

### 03_Visual_Inspection_Agent
The prompt is now fully in English, and so is every output: summary, accident description, causes. `damaged_items` only uses the shared part codes (with left and right seen from the driver's seat), so the plausibility agent and the score can compare them with the invoice. The model is unchanged.

### 05_Incident_Plausibility_Agent
- **The address is now found on the map.** Before, the whole address ("Avenue el Bassatine, L'aouina, 2045 Tunis, Tunisia") was sent to OpenStreetMap as one search, which found nothing, so the map and weather checks were skipped ("a map or weather service was unavailable"). The new **Address variants** node tries, in order: street + city + country, street + country, postal code, then the city alone. The first one found is used. A street gives the road checks (traffic lights, roundabouts, speed); even the city alone gives the weather and daylight checks.
- The summary now says which check was skipped and why.
- It still uses your local models (fine-tuned `claimshield-recon` and `qwen2.5:3b`), so **Ollama must be running**. The trigger is renamed "When called by the validation agent".

### RAG Agent & LLM-as-a-Judge Pipeline (02): now on local gemma2
Groq's free tier stopped the RAG with "Rate limit reached", so all three LLM steps (answer, judge, search terms) now use **gemma2:latest** in Ollama: no key and no rate limit.
gemma2 cannot call tools, so the AI Agent was replaced by three nodes that do the same job in one shot:
**Search Policy Clauses** (the same Qdrant collection, embeddings and Cohere reranker) → **Policy Clauses** (puts the 4 best clauses and the rules into one prompt) → **Policy Answer** (gemma2 writes the answer).
The judge, the retry with better search terms and **Coverage Result** are unchanged. On a CPU, gemma2 takes about a minute per answer.

### 03 Invoice Parser
Unchanged since the previous version.

### 04b_Agent_Test_Runner
26 tests. The policy tests were removed, and two were added: parts compared by code, and an unreadable invoice total. **All 26 pass.**

## 3. Install and set up (one time)

### 3.1 Install
1. Start Docker Desktop and Ollama (with `gemma2:latest`, `qwen2.5:3b` and `claimshield-recon`). In PowerShell, from `C:\Users\pc\Documents\ClaimshieldAi`, run `docker compose up -d`.
2. Double-click **`integration\install.cmd`**. It:
   - backs up your workflows to `data\integration\backup\`
   - unpublishes the old orchestrator
   - adds the **Ollama (local)** credential (http://host.docker.internal:11434) used by the RAG
   - imports the 6 workflows (same IDs, so they **replace** the old versions)
   - publishes 04, Visual, Invoice, Plausibility and RAG
   - restarts n8n
3. Open http://localhost:5678 and refresh the page.

### 3.2 Set the insurer email
Open **04_Validation_Fraud_Decision_Agent**, then double-click **Write Messages**. At the top, change:
- `insurer_email`: who receives the insurer message (for example your own address, for the demo)
- `from_email`: the address you send from (the Gmail address of 3.3)

Click **Publish** at the top right.

### 3.3 Make the emails really go out (Gmail, about 5 minutes)
1. Go to your Google Account → **Security**. Turn on **2-Step Verification** if it is off, then open **App passwords**. Create one named "n8n" and copy the 16-character password.
2. In n8n, in workflow 04, double-click **Email to Client**. Under Credential, choose **Create new credential** and enter:
   - User: your Gmail address
   - Password: the app password
   - Host: `smtp.gmail.com`
   - Port: `465`
   - SSL/TLS: on

   Click **Save**.
3. Double-click **Email to Insurer** and select the same credential.
4. Click **Publish**.

Skipping this is fine for a demo: both messages still appear on the result page, marked "Email not sent".

### 3.4 Delete the old orchestrator
In the n8n workflow list, open the "…" menu on **00_ClaimShield_Orchestrator** and choose **Archive**, then delete it. Also delete `Workflows\00_ClaimShield_Orchestrator.json` from the repo if it is still there.

## 4. Run the demo
Open **http://localhost:5678/webhook/claim**. Each claim takes a few minutes, because the agents run one after the other and the plausibility agent runs on your machine. The page waits, then shows the result by itself.

| Scenario | What to enter | Expected |
|---|---|---|
| A. Rejected | A date in the future | **Rejected**, with the reason. No AI call. |
| B. Normal claim | A recent date and hour, a real street and city, a description that matches the photos (for example "A car hit my rear bumper at a red light"), 2 or 3 **new** photos, `data\invoices\INV-001.pdf` | **Auto-approved** if everything is consistent and the total is under 2000 TND. Otherwise **Human review**, with the reasons. The client message explains the policy for the case. |
| C. Fraud | The same photos as B again, with any story | **Fraud investigation**: PHOTO_REUSED (+40) in the insurer message. The client only reads "Under review". |
| D. Inconsistent story | A description that contradicts the photos (for example a front impact while the photos show the rear) | DAMAGE_MISMATCH (+20) and usually **Human review**. |
| E. Story vs weather | "It was raining heavily" on a dry day at a real street | INCIDENT_IMPLAUSIBLE from the plausibility agent (weather contradiction). |

**What to show in n8n:** in **Executions**, open the run of workflow 04. The path the claim took is green: form → validation → the 4 agents → score → messages. Each agent also has its own run.

## 5. Good to know
- **After editing any of these workflows, click Publish.** The form uses the published versions.
- **Photos are remembered** in the Data Table "photo hashes", so a photo submitted twice is always flagged. To reset the demo, delete the rows in Overview → Data tables → photo hashes, but keep the row `CLM-H001`, which the tests use.
- **The invoice must have real text, not a scan.** Scans need LlamaParse, whose key `LLAMA_CLOUD_API_KEY` is not passed into the container. With a scan, the OCR agent fails, the plausibility agent gets no parts, and the claim goes to human review.
- **Free API limits** (Gemini, Groq, NVIDIA) can make one agent fail. The claim then goes to human review instead of crashing. The RAG and the plausibility agent run locally, so they have no such limit.
