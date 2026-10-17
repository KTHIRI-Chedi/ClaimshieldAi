# Invoice Parser Agent (`03_Invoice_Parser_Agent`)

## Flow
1. **Input**: `file_path`, `invoice_path` or `claim.invoice_path` of a file under `/data` (PDF, JPG or PNG), from the manual trigger or from the orchestrator through *Execute Workflow*.
2. **Check File Found**: if the file does not exist, the workflow returns `{ error: true, reason: "Invoice file not found: <path>" }` through **Error Result**. LlamaParse failures and a part failing on both LLMs end the same way, so the orchestrator never crashes and sends the claim to human review.
3. **Native extraction** (`Extract From File`): the text layer of a PDF is used directly only if it contains the amounts (≥ 50 characters and ≥ 2 amounts). Scans, photos and PDFs whose text is only a header or footer go to OCR.
4. **OCR**: LlamaParse **v2 API** (`/api/v2/parse`, tier `cost_effective`). The file is uploaded, `job.status` is polled every 3 s until `COMPLETED`, then the result is fetched with `?expand=markdown_full`.
5. **LLM reliability**:
   - **Normalize Numbers**: French amounts (`410,000` TND, `1.190,500`) are converted to dot decimals (`410.00`, `1190.50`) before the LLM, which otherwise reads a decimal comma as a thousands separator. English-format documents are left as is.
   - **Split Into Chunks**: invoices longer than ~1,500 characters are cut between table rows, with one LLM call per part. The parts are merged in **Merge Chunks**: header fields come from the first part, totals from the last one, and the lines are concatenated. Short outputs mean no forgotten lines and no timeouts on long invoices.
   - **Fallback**: if the primary extractor fails for a part (timeout or invalid JSON), that part goes to the **Fallback Extractor** (`nvidia/nemotron-3-super-120b-a12b`, 60 s, 2 attempts). `extraction.llm_fallback_used` and `extraction.chunks` appear in the output.
6. **Information Extractor** (primary: NVIDIA NIM `openai/gpt-oss-20b`, credential `NVIDIA_NIM_Free`, 120 s timeout, `reasoningEffort: low`): turns the text into structured JSON, with numbers copied exactly as printed and French formats handled (`1 190,500`). It covers line items (category, line discounts, VAT rate per line), labor, global discount, Total HT, single or multiple VAT, tax-inclusive (TTC) prices, other charges (timbre fiscal), and `is_invoice`.
7. **Arithmetic Check** (Code, deterministic) returns a `status`:
   - `ok`;
   - `arithmetic_mismatch`: `risk_points = 15`, details in `arithmetic_check.issues` (line, labor, subtotal, net, VAT, tax base, total);
   - `needs_review`: not an invoice, no line items or no total. `risk_points = 0`, reasons in `review_reasons`. An unreadable document is not a fraud signal.

   The output starts with the fields read by the Fraud Risk & Decision agent: `error`, `totals_match` (`true`, `false`, or `null` for needs_review), `arithmetic_issue` (readable text or `null`), and `line_items[]` as `{ part, type: part|labor|other, quantity, unit_price, line_total }`. See the contract in `INTEGRATION.md`.

   Tolerance: max(0.05, 0.1 % of the amount). Labor that is also listed as a line item is not counted twice. Lines without a quantity or unit price are listed in `unchecked_lines`.

## Setup
```bash
cp .env.example .env              # then put LLAMA_CLOUD_API_KEY=llx-... in .env
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
INV_PRIMARY_MODEL=invalid/model python scripts/test_invoice_agent.py INV-001.pdf   # force the fallback LLM
python scripts/build_invoice_workflow.py           # then rebuild and reimport the normal workflow
```
For each file, the script reimports the workflow with that file as the default input, runs it, compares the result with `expected.json` (status, extraction method, total, number of lines), and finally restores `INV-001.pdf` as the default. ⚠️ It overwrites the workflow in n8n, so save your manual edits in the builder first.

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
