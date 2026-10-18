# Fine-tuning the reconstruction model (Qwen2.5-3B + QLoRA)

This folder fine-tunes **Qwen2.5-3B-Instruct** with **QLoRA** to do the agent's *Reconstruct incident* step, then runs it on your computer's CPU with Ollama, called from n8n.

| File | What it is |
|---|---|
| `scenarios.js` | Scenario library: 12 incident types plus vague claims, in English, French and Arabic, with the correct labels for each |
| `generate_dataset.js` | Builds `data/train.jsonl`, `valid.jsonl`, `test.jsonl` (2,000 / 150 / 200 examples) |
| `finetune_qwen_qlora.ipynb` | Colab notebook: baseline evaluation, QLoRA training, evaluation after training, GGUF export |
| `Modelfile` | Ollama recipe for the exported model (the notebook also writes one) |
| `build_notebook.py` | Regenerates the notebook if you edit its cells |

## Why this design (for the report)

- **What is fine-tuned:** the reconstruction step. It turns a claim description into the collision scenario, impact zone, parts that should be damaged, severity, quoted contradictions, and abstains when the story is too vague.
- **Why a 3B model:** it runs on a laptop CPU, with no GPU and no rate limits, and claim data stays local (design section 3). Fine-tuning helps small models the most.
- **Labels correct by construction:** each example starts from a scenario specification (scenario, side hit, speed, contradictions…). The labels come from that specification, and the description is written from it. The model doesn't learn a teacher model's mistakes.
- **What the data teaches:**
  - **Abstention:** 7% vague claims.
  - **Contradictions with exact quotes:** about 15%.
  - **Hedged details, which are not contradictions:** about 15%.
  - **Ignoring prompt injections:** 5%.
  - **Reading the text when an extracted fact is missing:** 12%.
  - **Three languages:** EN 45% · FR 35% · AR 20%.
- **Same prompt in training and in production:** the dataset is built with the `reconstruction-ft1` prompt file, the same one the workflow sends. It's short (268 characters, no examples), which matters on a CPU.
- **QLoRA settings:**
  - base weights frozen in 4-bit NF4;
  - LoRA r = 16, α = 32 on `q,k,v,o,gate,up,down`;
  - 2 epochs, learning rate 2e-4 with cosine decay, effective batch 16, 8-bit AdamW;
  - loss computed on the answer only, not on the prompt.

## Step 1: Generate the dataset (on your computer, 5 seconds)

From the `incident-plausibility` folder:
```powershell
node dev/finetune/generate_dataset.js
```
This writes `dev/finetune/data/train.jsonl`, `valid.jsonl`, `test.jsonl` and `stats.json` (the numbers for the report). Every example is checked: the answer matches the schema, and every contradiction quote is in the description.

**Optional, for more natural wording:** let an LLM rewrite some descriptions. Sentences that labels quote are kept word for word, and a rewrite is rejected if they changed.
```powershell
$env:LLM_API_KEY="gsk_..."; node dev/finetune/generate_dataset.js --paraphrase 300 --provider groq
```
With the free tier's rate limits, this takes about 30 minutes for 300 examples.

## Step 2: Train on Colab (free T4 GPU, about 40–60 minutes)

1. Go to **colab.research.google.com**, then **File → Upload notebook**, and choose `dev/finetune/finetune_qwen_qlora.ipynb`.
2. **Runtime → Change runtime type → T4 GPU → Save.**
3. **Runtime → Run all.** When cell 3 asks for files, upload `train.jsonl`, `valid.jsonl` and `test.jsonl` from `dev/finetune/data/`.
4. Watch the results:
   - **Cell 6 (baseline):** the model before training. Expect few valid answers, because the short prompt doesn't explain the format.
   - **Cell 8:** prints the masked labels. Only the JSON answer should appear.
   - **Cell 9:** training, then the loss curve. Both curves should go down and level off.
   - **Cell 10:** the before/after table.
   - **Cell 12:** builds the GGUF file. The first time, it takes several minutes.
5. **Cell 13** downloads `claimshield-recon-Q4_K_M.gguf` (about 2 GB), `Modelfile`, `claimshield-recon-lora.zip`, `before_after.csv` and `loss_curve.png`. If the browser download of the large file fails, use the Google Drive lines at the end of that cell.

If Colab disconnects, run all cells again: the dataset is small and training restarts from scratch.

## Step 3: Run the model on your computer with Ollama

1. Install **Ollama for Windows** from ollama.com. It runs natively, using the CPU and normal RAM; no GPU is needed.
2. Put `claimshield-recon-Q4_K_M.gguf` and `Modelfile` in one folder, open PowerShell there, and run:
   ```powershell
   ollama create claimshield-recon -f Modelfile
   ollama pull qwen2.5:3b
   ```
   The second command downloads the original model, which the comparison uses as the "before".
3. Quick test:
   ```powershell
   ollama run claimshield-recon "test"
   ```
4. **Let n8n (in Docker) reach Ollama.** n8n calls `http://host.docker.internal:11434`. If n8n reports "connection refused", make Ollama listen on all interfaces, then quit Ollama from the tray icon and start it again:
   ```powershell
   setx OLLAMA_HOST 0.0.0.0
   ```

## Step 4: Use it in the n8n workflow

1. Import the latest `incident_plausibility_agent.json`. Keep your credential in both LLM nodes; Ollama ignores the key.
2. Open the **LLM settings** node and change:
   ```js
   const PROVIDER = {
     extraction: 'groq',          // reading the story stays on Groq
     reconstruction: 'ollama',    // the fine-tuned model on your CPU
   };
   const RECONSTRUCTION_PROMPT = 'ft1';   // the short prompt the model was trained with
   ```
   The Ollama preset already uses the model `claimshield-recon`. When the two steps use different providers, the free-tier pause is skipped automatically.
3. **Test workflow.** On a laptop CPU, each reconstruction answer takes roughly 20–60 seconds. For quick tests, set `RECONSTRUCTION_SAMPLES = 1`.

## Step 5: The comparison for the report

Run the same 15 hand-written test claims (`dev/eval/claims.json`, never used in training) through four setups. The extraction runs once per claim on Groq and is reused:

```powershell
$env:LLM_API_KEY="gsk_..."
node dev/eval/run_eval.js --ext-provider groq --configs "v3+ft1@ollama:qwen2.5:3b,v3+v2@ollama:qwen2.5:3b,v3+ft1@ollama:claimshield-recon,v3+v2@groq"
```

| Column | What it shows |
|---|---|
| `ft1 @ qwen2.5:3b` | Base 3B with the short prompt (zero-shot) |
| `v2 @ qwen2.5:3b` | Base 3B with the full few-shot prompt: what **prompt engineering** alone gets |
| `ft1 @ claimshield-recon` | **Fine-tuned 3B** with the short prompt: what **fine-tuning** adds |
| `v2 @ groq` | gpt-oss-120b with the few-shot prompt: the large-model reference |

The report (`dev/eval/results/<date>.md`) gives impact-zone accuracy, contradiction TP/FP/FN, invented contradictions rejected by the quote check, abstention, and **seconds per claim**. Running 3 local configurations on a CPU takes a while (15 claims × 3 answers each), so start it and let it run.

**In the report, show:**
- the dataset design and `stats.json`;
- the QLoRA settings and the number of trainable parameters (printed in cell 5);
- the loss curve;
- the synthetic before/after table (`before_after.csv`);
- the 4-way table above;
- the limitations below.

## Limitations to report honestly
- **Template wording.** Real claimants write more varied text. The 15 hand-written claims are the real test of generalisation, and the `--paraphrase` option reduces the gap.
- **The synthetic test set comes from the same generator as the training set,** so the notebook's before/after table is optimistic. The 4-way comparison on hand-written claims is the fair one.
- **A 3B model reasons about collisions less well than a 120B model.** The fine-tuned model may win on format, quotes and abstention, and lose on unusual stories. Report whichever happens.
- **Training needs a GPU, so it runs on Colab.** n8n only calls the finished model.
