# Invoice Parser Agent (`03_Invoice_Parser_Agent`)

> **Merged version (Fedi + Omar).** Omar's agent (rich invoice schema, grounding check, chunking, fallback LLM, `needs_review`)
> with Fedi's additions: file **or** path input, prompt-technique switch (**Few-Shot** by default, chosen by evaluation),
> Self-Consistency vote, per-amount ×1000/×100 misread correction, fraud signals (`warnings`), LlamaParse credential,
> a fixed number normalizer, and the evaluation workflow `03b_Invoice_Agent_Evaluation` on 38 labelled invoices.

## Flow
1. **Input** (either works): the invoice **file itself** sent as binary data by the caller (any field name; PDF, JPG or PNG), **or** a path under `/data` in `file_path`, `invoice_path` or `claim.invoice_path`. The claim (`claimed_amount`, `incident_date`), sent as `claim` or as flat fields, is kept for the fraud signals. Optional `technique` overrides the prompt technique (used by the evaluation).
2. **Check File Found**: if the file does not exist, the workflow returns `{ error: true, reason: "Invoice file not found: <path>" }` through **Error Result**. LlamaParse failures and a part failing on both LLMs end the same way, so the orchestrator never crashes and sends the claim to human review.
3. **Native extraction** (`Extract From File`): the text layer of a PDF is used directly only if it contains the amounts (≥ 50 characters and ≥ 2 amounts). Scans, photos and PDFs whose text is only a header or footer go to OCR.
4. **OCR**: LlamaParse **v2 API** (`/api/v2/parse`, tier `cost_effective`). The file is uploaded, `job.status` is polled every 3 s until `COMPLETED`, then the result is fetched with `?expand=markdown_full`.
5. **LLM reliability**:
   - **Normalize Numbers**: every amount becomes a plain number with a dot decimal before the LLM, number by number: English `1,850.450` → `1850.45`, French `1.602,037` / `1 602,037` → `1602.037` / `1 602.037`, TND `450.000` → `450.00` (spaces between groups are kept: they may separate two table cells). The first version broke English-format TND amounts (`1,850.450` → `1.85.450`); the fix keeps 483/483 printed amounts of the test set findable (446/483 before).
   - **Split Into Chunks**: invoices longer than ~1,500 characters are cut between table rows, with one LLM call per part. The parts are merged in **Merge Chunks**: header fields come from the first part, totals from the last one, and the lines are concatenated. Short outputs mean no forgotten lines and no timeouts on long invoices.
   - **Prompt Technique**: `zero_shot` | `few_shot` (default) | `cot` | `self_consistency`, set by `DEFAULT_TECHNIQUE` at the top of the node (or `INV_TECHNIQUE` when building). Few-Shot adds two worked examples (English TND invoice; French invoice with line discount, global discount, timbre fiscal and a dd/mm/yyyy date). Self-Consistency reads each part 3 times at temperature 0.7 and **Merge Chunks** votes field by field (`extraction.agreement`).
   - **Fallback**: if the primary extractor fails for a part (timeout or invalid JSON), that part goes to the **Fallback Extractor** (`nvidia/nemotron-3-super-120b-a12b`, 60 s, 2 attempts). `extraction.llm_fallback_used` and `extraction.chunks` appear in the output.
6. **Information Extractor** (primary: NVIDIA NIM `meta/llama-3.2-11b-vision-instruct`, credential `NVIDIA_NIM_Free`, 120 s timeout; change with `INV_PRIMARY_MODEL`, e.g. `openai/gpt-oss-20b`): turns the text into structured JSON, with numbers copied exactly as printed and French formats handled (`1 190,500`). It covers line items (category, line discounts, VAT rate per line), labor, global discount, Total HT, single or multiple VAT, tax-inclusive (TTC) prices, other charges (timbre fiscal), and `is_invoice`.
7. **Arithmetic Check** (Code, deterministic). It first corrects **×1000 / ×100 misreads** amount by amount (an amount not printed whose /1000 or /100 is printed; listed in `extraction.corrected_amounts`), then runs a **grounding check**: every amount returned by the LLM must appear in the invoice text (spaced thousands like `1 043.20` are handled). Amounts that are not printed (recomputed, "corrected" or invented by the LLM) are listed in `ungrounded_amounts` and are not trusted: the checks that depend on them are skipped, so `arithmetic_issue` only quotes numbers printed on the invoice. It then returns a `status`:
   - `ok`;
   - `arithmetic_mismatch`: `risk_points = 15`, details in `arithmetic_check.issues` (line, labor, subtotal, net, VAT, tax base, total);
   - `needs_review`: not an invoice, no line items, no total, or ungrounded amounts with no other evidence. `risk_points = 0`, reasons in `review_reasons`. An unreadable document is not a fraud signal.

   It also returns **fraud signals** in `warnings[]` (claimed amount ≠ invoice total, invoice dated before the incident, a line listed twice) and `amount_matches_claim`. They need the claim from the orchestrator; they add no arithmetic points.

   The output starts with the fields read by the Fraud Risk & Decision agent: `error`, `totals_match` (`true`, `false`, or `null` for needs_review), `arithmetic_issue` (readable text or `null`), and `line_items[]` as `{ part, type: part|labor|other, quantity, unit_price, line_total }`. See the contract in `INTEGRATION.md`.

   Tolerance: max(0.05, 0.1 % of the amount). Labor that is also listed as a line item is not counted twice. Lines without a quantity or unit price are listed in `unchecked_lines`.

## Setup
LlamaParse key: create an n8n credential **`LlamaParse API`** (type *Header Auth*, name `Authorization`, value `Bearer llx-...`); the builder finds it by name. Without it, the workflow falls back to `$env.LLAMA_CLOUD_API_KEY` (needs `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, which lets every workflow read all environment variables, so the credential is preferred).
```bash
cp .env.example .env              # only for the $env fallback: LLAMA_CLOUD_API_KEY=llx-...
docker compose up -d
pip install -r scripts/requirements.txt
python scripts/generate_test_invoices.py   # test invoices -> data/invoices/
python scripts/build_invoice_workflow.py   # regenerates the workflow JSON
docker cp workflows/03_Invoice_Parser_Agent.json claimshield_n8n:/tmp/inv.json
docker exec claimshield_n8n n8n import:workflow --input=/tmp/inv.json
```

## Automated tests
```bash
python scripts/test_invoice_agent.py               # all invoices + missing-file case
python scripts/test_invoice_agent.py INV-005.pdf   # a single file
python scripts/run_invoice_agent.py data/invoices/real/x.pdf   # any file, e.g. a real invoice (see data/invoices/real/README.md)
INV_PRIMARY_MODEL=invalid/model python scripts/test_invoice_agent.py INV-001.pdf   # force the fallback LLM
python scripts/build_invoice_workflow.py           # then rebuild and reimport the normal workflow
```
For each file, the script reimports the workflow with that file as the default input, runs it, compares the result with `expected.json` (status, extraction method, total, number of lines), and finally restores `INV-001.pdf` as the default. ⚠️ It overwrites the workflow in n8n, so save your manual edits in the builder first.

## Evaluation workflow (`03b_Invoice_Agent_Evaluation`, id `InvAgentEval03b`)
Runs the published agent on **38 labelled invoices** (`data/eval_invoices/` 26 + `data/invoices/` 12, answers in `data/eval_invoices/ground_truth.json`) for each prompt technique listed in **Settings**, and saves `<run>_report.md`, `_metrics.json` and `_cases.csv` in `data/eval_results/`.
Metrics: verdict accuracy (ok / mismatch / review), errors auto-approved (must be 0), false fraud flags, unneeded reviews, error detection precision/recall/F1 + confusion matrix, error type, fraud-warning F1, line-item F1, quantity / unit price / type accuracy, field accuracy, document exact match, ×1000 misread rate, total MAE, ROUGE-L on part names, Self-Consistency agreement, LLM calls and latency per invoice, failure rate, prompt injection (verdict protected / extraction manipulated).
The 26 `eval_invoices` cover English, French and EUR formats, discounts, each arithmetic error type (line, subtotal, VAT, total), the three fraud signals, scans, a photo and a hidden prompt injection.

## Test invoices (`data/invoices/`)
| File | Type | Case | Expected status |
|---|---|---|---|
| INV-001.pdf | text | simple | ok |
| INV-002.pdf | text | subtotal inflated by 450 | arithmetic_mismatch |
| INV-003_scanned.pdf | scan | simple | ok |
| INV-004_scanned.pdf | scan | line total inflated by 300 | arithmetic_mismatch |
| INV-005.pdf | text | TND format (3 decimals), line discounts in %, timbre fiscal | ok |
| INV-006.pdf | text | global discount + timbre, total inflated by 200 | arithmetic_mismatch |
| INV-007.pdf | text | VAT 19 % + 7 %, labor as a line item | ok |
| INV-008.pdf | text | tax-inclusive (TTC) prices | ok |
| INV-009.pdf | text | 2 pages, 48 lines | ok |
| INV-010_photo.png | PNG photo | labor as a line item, timbre | ok |
| INV-011_mixed.pdf | scan + text footer | must go to OCR | ok |
| INV-012.pdf | text | claim letter, not an invoice | needs_review |

To test a file in the n8n UI, change the default value in the **Invoice Input** node.
