"""Build workflows/03_Invoice_Parser_Agent.json (importable n8n workflow).

Flow: input -> read file (error if missing) -> native PDF text extraction
  -> usable text layer (PDF with >= 2 amounts in its text)?
       yes -> use native text
       no  -> LlamaParse OCR v2 (upload -> poll status -> fetch markdown); also handles JPG/PNG
  -> Normalize Numbers (French amounts -> dot decimals)
  -> Split Into Chunks (long invoices: ~1500-char parts cut between rows)
  -> Information Extractor (NVIDIA, one call per part)
       on error -> Fallback Extractor (second NVIDIA model, other family) for that part
  -> Merge Chunks (one invoice JSON)
  -> Arithmetic Check (Code): status ok | arithmetic_mismatch | needs_review

Usage: python scripts/build_invoice_workflow.py [default_file_path]
Env: INV_PRIMARY_MODEL / INV_FALLBACK_MODEL override the model ids (e.g. an invalid primary forces the fallback).
"""
import json
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "workflows" / "03_Invoice_Parser_Agent.json"
LLAMA = "https://api.cloud.llamaindex.ai/api/v2/parse"  # v1 is disabled for new accounts
LLAMA_CONFIG = '{"tier": "cost_effective", "version": "latest"}'
DEFAULT_FILE = "/data/invoices/INV-001.pdf"
AUTH = {"parameters": [{"name": "Authorization", "value": "=Bearer {{ $env.LLAMA_CLOUD_API_KEY }}"}]}
NVIDIA_CRED = {"openAiApi": {"id": "SPONP3X9OugaVEBi", "name": "NVIDIA_NIM_Free"}}
PRIMARY_MODEL = os.environ.get("INV_PRIMARY_MODEL", "openai/gpt-oss-20b")
FALLBACK_MODEL = os.environ.get("INV_FALLBACK_MODEL", "nvidia/nemotron-3-super-120b-a12b")  # other model family
CHUNK_CHARS = 1500

NUM = {"type": "number"}
INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_invoice": {"type": "boolean",
                       "description": "false if the document is not a repair invoice (letter, quote, report...)"},
        "invoice_number": {"type": "string"},
        "garage_name": {"type": "string"},
        "invoice_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
        "vehicle_plate": {"type": "string"},
        "claim_ref": {"type": "string"},
        "currency": {"type": "string"},
        "prices_include_tax": {"type": "boolean",
                               "description": "true if line prices and amounts are tax-inclusive (TTC)"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "category": {"type": "string", "enum": ["part", "labor", "paint", "consumable", "other"]},
                    "quantity": NUM,
                    "unit_price": NUM,
                    "discount_percent": {"type": "number", "description": "Line discount in %, if printed"},
                    "discount_amount": {"type": "number", "description": "Line discount amount, if printed"},
                    "vat_rate": {"type": "number", "description": "VAT rate in % for this line, if printed"},
                    "line_total": {"type": "number", "description": "Line amount exactly as printed"},
                },
                "required": ["description", "line_total"],
            },
        },
        "labor": {
            "type": "object",
            "description": "Only if labor is printed OUTSIDE the line items table",
            "properties": {"hours": NUM, "rate": NUM, "total": NUM},
        },
        "subtotal": {"type": "number",
                     "description": "Sum of lines before global discount and tax (Sous-total, Total brut)"},
        "discount_total": {"type": "number", "description": "Global discount amount (positive), if printed"},
        "net_before_tax": {"type": "number",
                           "description": "Amount before tax after discounts (Total HT, Net HT line), if printed. Never a per-rate tax base"},
        "vat_rate": {"type": "number", "description": "VAT rate in %, if a single rate is used"},
        "vat": {"type": "number", "description": "VAT amount, if a single rate is used"},
        "tax_lines": {
            "type": "array",
            "description": "One entry per tax rate when several rates are printed",
            "items": {"type": "object",
                      "properties": {"label": {"type": "string"}, "rate": NUM, "base": NUM, "amount": NUM}},
        },
        "other_charges": {
            "type": "array",
            "description": "Charges added on top (timbre fiscal / stamp duty, fees, towing...)",
            "items": {"type": "object", "properties": {"label": {"type": "string"}, "amount": NUM}},
        },
        "total": {"type": "number", "description": "Grand total to pay (Total TTC, Net a payer), as printed"},
    },
    "required": ["is_invoice"],
}

SYSTEM_PROMPT = """You extract data from documents submitted as vehicle repair invoices for an insurance claims system.
Rules:
- Copy every number EXACTLY as printed, even if it looks wrong. Never recompute, fix or infer amounts: a separate step checks the arithmetic.
- Amounts are already normalized to a dot decimal separator ("1 190.500" means 1190.5); spaces inside a number are thousands separators only within the same table cell. Output plain JSON numbers.
- If a value is not printed, omit the field. Never invent a quantity or unit price.
- If labor appears as a row of the items table, keep it as a line item with category "labor" and do not fill the labor object.
- Put stamp duty (timbre fiscal) and other fees added after tax in other_charges, not in line_items.
- Set is_invoice to false if the document is not an invoice (letter, quote/devis, report, form).
- The text may be one part of a longer invoice: extract only what is printed in that part, and omit header or total fields that are not in it."""

CHECK_FILE_JS = """const items = $input.all();
const index = items.findIndex((i) => i.binary?.data);
if (index === -1) {
  throw new Error(`Invoice file not found: ${$('Invoice Input').first().json.file_path}`);
}
return [{ json: items[index].json, binary: items[index].binary, pairedItem: { item: index } }];"""

DETECT_JS = """// Use the native text only for PDFs whose text layer actually contains the amounts.
// Scans, photos and PDFs with only a text header go to OCR.
const binary = $('Check File Found').item.binary;
const isPdf = (binary.data.mimeType || '').includes('pdf') || /\\.pdf$/i.test(binary.data.fileName || '');
const text = isPdf ? String($json.text || '').trim() : '';
const amounts = (text.match(/\\d[\\d\\s.,]*[.,]\\d{2,3}(?!\\d)/g) || []).length;
return {
  json: {
    file_path: $('Invoice Input').first().json.file_path,
    file_type: binary.data.mimeType,
    invoice_text: text,
    has_text_layer: text.replace(/\\s/g, '').length >= 50 && amounts >= 2,
  },
  binary,
};"""

NORMALIZE_JS = r"""// French amounts ("410,000" TND = 410.0, "1.190,500") are turned into dot decimals before the LLM,
// which otherwise reads a decimal comma as a thousands separator. English-format documents are left as is.
let text = String($json.invoice_text || '');
const english = /\d,\d{3}\.\d{2}(?!\d)/.test(text);
if (!english) {
  text = text.replace(/\b\d{1,3}(?:\.\d{3})+,\d{1,3}(?!\d)/g, (m) => m.replace(/\./g, ''));
  // Drop trailing zeros beyond 2 decimals so "1,000" becomes "1.00", never the ambiguous "1.000"
  text = text.replace(/(\d),(\d{1,3})(?!\d)/g, (m, i, d) => `${i}.${d.length > 2 ? d.replace(/0+$/, '').padEnd(2, '0') : d}`);
}
return { json: { ...$json, invoice_text: text, number_format: english ? 'en' : 'fr' } };"""

POLL_JS = """const status = $json.job?.status;
if (['FAILED', 'CANCELLED'].includes(status)) throw new Error(`LlamaParse job ${status}`);
if ($runIndex > 40) throw new Error('LlamaParse timeout (job still pending)');
return { json: { ...$json, done: status === 'COMPLETED' } };"""

SPLIT_JS = r"""// Long invoices are split into parts cut between rows, one LLM call per part: short outputs mean
// no dropped lines and no timeouts. "Merge Chunks" puts the parts back together.
const MAX_CHARS = __CHUNK_CHARS__;
const src = $input.first().json;
const lines = String(src.invoice_text || '').split('\n');
const insideRow = /^\s*(<\/?(td|th)\b|<\/tr>)/i; // never cut inside an HTML table row (OCR markdown)
const chunks = [];
let current = [];
for (const line of lines) {
  if (current.length && !insideRow.test(line) && current.join('\n').length + line.length > MAX_CHARS) {
    chunks.push(current.join('\n'));
    current = [];
  }
  current.push(line);
}
if (current.length) chunks.push(current.join('\n'));
return chunks.map((text, i) => ({
  json: {
    ...src,
    chunk_index: i,
    chunk_count: chunks.length,
    invoice_text: chunks.length > 1 ? `[Part ${i + 1} of ${chunks.length} of the same invoice]\n${text}` : text,
  },
  pairedItem: { item: 0 },
}));"""

MERGE_JS = r"""// Rebuild one invoice from the per-part extractions (primary or fallback LLM), in part order.
// Header fields come from the first part that has them, totals from the last one.
const failed = $input.all().find((item) => item.json.error);
if (failed) {
  const reason = `LLM extraction failed on primary and fallback models: ${failed.json.error?.message ?? failed.json.error}`;
  return [{ json: { error: reason } }];
}
const parts = $input.all().map((item, i) => {
  let index = i;
  try { index = $('Split Into Chunks').itemMatching(i).json.chunk_index; } catch (e) {}
  return { index, out: item.json.output || {} };
}).sort((a, b) => a.index - b.index).map((p) => p.out);

const HEADER = ['invoice_number', 'garage_name', 'invoice_date', 'vehicle_plate', 'claim_ref', 'currency',
  'prices_include_tax', 'labor'];
const TOTALS = ['subtotal', 'discount_total', 'net_before_tax', 'vat_rate', 'vat', 'tax_lines', 'other_charges', 'total'];
const present = (v) => v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0);

const invoice = { is_invoice: parts.some((p) => p.is_invoice !== false) };
for (const k of HEADER) { const p = parts.find((x) => present(x[k])); if (p) invoice[k] = p[k]; }
invoice.line_items = parts.flatMap((p) => p.line_items || []);
for (const k of TOTALS) { const p = [...parts].reverse().find((x) => present(x[k])); if (p) invoice[k] = p[k]; }

return [{
  json: {
    output: invoice,
    chunks: parts.length,
    llm_fallback_used: $('Fallback Extractor').isExecuted,
  },
}];"""

ERROR_JS = r"""// Any failure before extraction (missing file, OCR) ends here: the orchestrator gets { error: true }
// and sends the claim to human review instead of the whole run crashing.
const first = $input.first().json;
const reason = String(first.error?.message ?? first.error ?? first.message ?? 'Unknown error');
let sourceFile = null;
try { sourceFile = $('Invoice Input').first().json.file_path; } catch (e) {}
return [{
  json: {
    agent: 'invoice_parser', error: true, reason, source_file: sourceFile,
    status: 'error', totals_match: null, arithmetic_issue: null, line_items: [], claimed_parts: [],
  },
}];"""

CHECK_JS = """// Deterministic arithmetic check on the extracted invoice.
// status: ok | arithmetic_mismatch (+15 risk points) | needs_review (not an invoice / incomplete, 0 points)
if ($json.error) {
  return {
    json: {
      agent: 'invoice_parser', error: true, reason: String($json.error),
      source_file: $('Invoice Input').first().json.file_path,
      status: 'error', totals_match: null, arithmetic_issue: null, line_items: [], claimed_parts: [],
    },
  };
}
const inv = $json.output || {};
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const round = (n) => Math.round(n * 1000) / 1000;
const close = (a, b) => Math.abs(a - b) <= Math.max(0.05, Math.abs(b) * 0.001);
const pct = (r) => (r > 1 ? r / 100 : r);
const sum = (arr, f) => arr.reduce((s, x) => s + (num(f(x)) ?? 0), 0);

const issues = [];
const reviewReasons = [];
const uncheckedLines = [];
const items = inv.line_items || [];

if (inv.is_invoice === false) reviewReasons.push('not_an_invoice');
if (!items.length) reviewReasons.push('no_line_items');
if (num(inv.total) == null) reviewReasons.push('no_total');

// 1. Each line: quantity x unit price, minus its discount
for (const li of items) {
  const qty = num(li.quantity);
  const price = num(li.unit_price);
  const printed = num(li.line_total);
  if (printed == null) { reviewReasons.push(`line_without_amount: ${li.description}`); continue; }
  if (qty == null || price == null) { uncheckedLines.push(li.description); continue; }
  const gross = qty * price;
  const candidates = [gross - (num(li.discount_amount) ?? 0)];
  if (num(li.discount_percent) != null) candidates.push(gross * (1 - pct(li.discount_percent)));
  if (!candidates.some((c) => close(c, printed))) {
    issues.push({ type: 'line_total_mismatch', item: li.description, printed, expected: round(candidates.at(-1)) });
  }
}

// 2. Labor printed outside the table (ignored if the same amount is also a "labor" line)
let laborTotal = num(inv.labor?.total) ?? 0;
if (num(inv.labor?.hours) != null && num(inv.labor?.rate) != null && !close(inv.labor.hours * inv.labor.rate, laborTotal)) {
  issues.push({ type: 'labor_mismatch', printed: laborTotal, expected: round(inv.labor.hours * inv.labor.rate) });
}
if (items.some((li) => li.category === 'labor' && close(num(li.line_total) ?? 0, laborTotal))) laborTotal = 0;

// 3. Subtotal, discount, net before tax
const linesSum = round(sum(items, (li) => li.line_total) + laborTotal);
const discount = num(inv.discount_total) ?? 0;
let base = linesSum - discount;
const subtotal = num(inv.subtotal);
if (subtotal != null) {
  if (close(subtotal, linesSum)) base = subtotal - discount;
  else if (discount && close(subtotal, linesSum - discount)) base = subtotal;
  else {
    issues.push({ type: 'subtotal_mismatch', printed: subtotal, expected: linesSum });
    base = subtotal - discount;
  }
}
const net = num(inv.net_before_tax);
if (net != null) {
  if (!close(net, base)) issues.push({ type: 'net_before_tax_mismatch', printed: net, expected: round(base) });
  base = net;
}

// 4. Taxes (one rate or several); with tax-inclusive prices the tax is informative only
const taxLines = inv.tax_lines || [];
for (const t of taxLines) {
  if (num(t.rate) != null && num(t.base) != null && num(t.amount) != null && !close(t.base * pct(t.rate), t.amount)) {
    issues.push({ type: 'tax_line_mismatch', label: t.label, printed: t.amount, expected: round(t.base * pct(t.rate)) });
  }
}
if (!inv.prices_include_tax) {
  if (taxLines.length && taxLines.every((t) => num(t.base) != null) && !close(sum(taxLines, (t) => t.base), base)) {
    issues.push({ type: 'tax_base_mismatch', printed: round(sum(taxLines, (t) => t.base)), expected: round(base) });
  }
  if (!taxLines.length && num(inv.vat) != null && num(inv.vat_rate) != null && !close(base * pct(inv.vat_rate), inv.vat)) {
    issues.push({ type: 'vat_mismatch', printed: inv.vat, expected: round(base * pct(inv.vat_rate)) });
  }
}
const tax = taxLines.length ? sum(taxLines, (t) => t.amount) : (num(inv.vat) ?? 0);

// 5. Grand total = net + tax + other charges (timbre fiscal...). Both the tax-exclusive and the
// tax-inclusive readings are accepted, so a wrong prices_include_tax flag from the LLM is not a fraud signal.
const charges = sum(inv.other_charges || [], (c) => c.amount);
const totals = [round(base + tax + charges), round(base + charges)];
const expectedTotal = inv.prices_include_tax ? totals[1] : totals[0];
if (num(inv.total) != null && !totals.some((t) => close(t, inv.total))) {
  issues.push({ type: 'total_mismatch', printed: inv.total, expected: expectedTotal });
}

const status = reviewReasons.length ? 'needs_review' : issues.length ? 'arithmetic_mismatch' : 'ok';

// Fields read by the Fraud Risk & Decision agent (team contract): totals_match, arithmetic_issue, line_items.
// type "other" (paint, consumables...) must not count as a part expected to be visible on the photos.
const fmt = (n) => (num(n) == null ? '?' : n.toFixed(2));
const LABELS = {
  line_total_mismatch: (i) => `Line "${i.item}"`, labor_mismatch: () => 'Labor', subtotal_mismatch: () => 'Subtotal',
  net_before_tax_mismatch: () => 'Total before tax', tax_line_mismatch: (i) => `Tax "${i.label}"`,
  tax_base_mismatch: () => 'Tax bases', vat_mismatch: () => 'VAT', total_mismatch: () => 'Grand total',
};
const arithmeticIssue = issues.length
  ? issues.map((i) => `${(LABELS[i.type] || (() => i.type))(i)}: printed ${fmt(i.printed)}, expected ${fmt(i.expected)}`).join('; ')
  : null;
const TYPES = { part: 'part', labor: 'labor' };
const lineItems = items.map((li) => ({
  part: li.description,
  type: li.category ? TYPES[li.category] || 'other' : 'part',
  quantity: num(li.quantity),
  unit_price: num(li.unit_price),
  line_total: num(li.line_total),
}));
if (laborTotal) {
  lineItems.push({ part: 'Labor', type: 'labor', quantity: num(inv.labor.hours), unit_price: num(inv.labor.rate), line_total: laborTotal });
}

return {
  json: {
    agent: 'invoice_parser',
    error: false,
    totals_match: status === 'needs_review' ? null : issues.length === 0,
    arithmetic_issue: arithmeticIssue,
    line_items: lineItems,
    status,
    risk_points: status === 'arithmetic_mismatch' ? 15 : 0,
    source_file: $('Invoice Input').first().json.file_path,
    extraction_method: $('Native Text').isExecuted ? 'native_pdf_text' : 'llamaparse_ocr',
    invoice: inv,
    claimed_parts: lineItems.filter((li) => li.type === 'part').map((li) => li.part),
    arithmetic_check: {
      ok: issues.length === 0,
      issues,
      unchecked_lines: uncheckedLines,
      computed_lines_sum: linesSum,
      computed_total: expectedTotal,
    },
    review_reasons: reviewReasons,
    extraction: { chunks: $json.chunks, llm_fallback_used: $json.llm_fallback_used },
  },
};"""


def node(name, type_, version, pos, params=None, **extra):
    return {"parameters": params or {}, "name": name, "type": type_, "typeVersion": version,
            "position": pos, "id": f"inv-{name.lower().replace(' ', '-')}", **extra}


def bool_if(expr):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": "c1", "leftValue": expr, "rightValue": "",
                            "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def set_fields(fields, include_other=True):
    return {
        "assignments": {"assignments": [
            {"id": f"a{i}", "name": k, "value": v, "type": "string"} for i, (k, v) in enumerate(fields.items())
        ]},
        "includeOtherFields": include_other,
        "options": {},
    }


def main_link(*targets):
    return {"main": [[{"node": t, "type": "main", "index": 0} for t in branch] for branch in targets]}


def build(default_file=DEFAULT_FILE):
    nodes = [
        node("Manual Trigger", "n8n-nodes-base.manualTrigger", 1, [0, 0]),
        node("When Called by Orchestrator", "n8n-nodes-base.executeWorkflowTrigger", 1.1, [0, 200],
             {"inputSource": "passthrough"}),
        node("Invoice Input", "n8n-nodes-base.set", 3.4, [220, 100],
             set_fields({"file_path": "={{ $json.file_path || $json.invoice_path || $json.claim?.invoice_path || '"
                         + default_file + "' }}"}, include_other=False)),
        node("Read Invoice File", "n8n-nodes-base.readWriteFile", 1, [440, 100],
             {"fileSelector": "={{ $json.file_path }}", "options": {"dataPropertyName": "data"}},
             alwaysOutputData=True),
        node("Check File Found", "n8n-nodes-base.code", 2, [660, 100], {"jsCode": CHECK_FILE_JS},
             onError="continueErrorOutput"),
        node("Extract PDF Text", "n8n-nodes-base.extractFromFile", 1, [880, 100],
             {"operation": "pdf", "binaryPropertyName": "data", "options": {}},
             onError="continueRegularOutput", alwaysOutputData=True),
        node("Detect Text Layer", "n8n-nodes-base.code", 2, [1100, 100],
             {"mode": "runOnceForEachItem", "jsCode": DETECT_JS}),
        node("Has Text Layer?", "n8n-nodes-base.if", 2.2, [1320, 100], bool_if("={{ $json.has_text_layer }}")),
        node("Native Text", "n8n-nodes-base.set", 3.4, [1560, 0],
             set_fields({"extraction_method": "native_pdf_text"})),
        node("LlamaParse Upload", "n8n-nodes-base.httpRequest", 4.2, [1560, 260], {
            "method": "POST", "url": f"{LLAMA}/upload",
            "sendHeaders": True, "headerParameters": AUTH,
            "sendBody": True, "contentType": "multipart-form-data",
            "bodyParameters": {"parameters": [
                {"parameterType": "formBinaryData", "name": "file", "inputDataFieldName": "data"},
                {"name": "configuration", "value": LLAMA_CONFIG},
            ]},
            "options": {},
        }, onError="continueErrorOutput"),
        node("Wait 3s", "n8n-nodes-base.wait", 1.1, [1780, 260], {"amount": 3}, webhookId="inv-wait-3s"),
        node("LlamaParse Job Status", "n8n-nodes-base.httpRequest", 4.2, [2000, 260], {
            "url": f"={LLAMA}/{{{{ $('LlamaParse Upload').first().json.id }}}}",
            "sendHeaders": True, "headerParameters": AUTH, "options": {},
        }, onError="continueErrorOutput"),
        node("Check Job Status", "n8n-nodes-base.code", 2, [2220, 260],
             {"mode": "runOnceForEachItem", "jsCode": POLL_JS}, onError="continueErrorOutput"),
        node("Job Done?", "n8n-nodes-base.if", 2.2, [2440, 260], bool_if("={{ $json.done }}")),
        node("LlamaParse Markdown", "n8n-nodes-base.httpRequest", 4.2, [2660, 200], {
            "url": f"={LLAMA}/{{{{ $('LlamaParse Upload').first().json.id }}}}?expand=markdown_full",
            "sendHeaders": True, "headerParameters": AUTH, "options": {},
        }, onError="continueErrorOutput"),
        node("OCR Text", "n8n-nodes-base.set", 3.4, [2880, 200],
             set_fields({"invoice_text": "={{ $json.markdown_full }}", "extraction_method": "llamaparse_ocr"},
                        include_other=False)),
        node("Normalize Numbers", "n8n-nodes-base.code", 2, [3100, 100],
             {"mode": "runOnceForEachItem", "jsCode": NORMALIZE_JS}),
        node("Split Into Chunks", "n8n-nodes-base.code", 2, [3320, 100],
             {"jsCode": SPLIT_JS.replace("__CHUNK_CHARS__", str(CHUNK_CHARS))}),
        # Primary LLM. Errors (timeout, invalid JSON) go to the error output -> fallback, per part.
        node("Information Extractor", "@n8n/n8n-nodes-langchain.informationExtractor", 1.2, [3560, 100], {
            "text": "={{ $json.invoice_text }}",
            "schemaType": "manual",
            "inputSchema": json.dumps(INVOICE_SCHEMA, indent=2),
            "options": {"systemPromptTemplate": SYSTEM_PROMPT},
        }, onError="continueErrorOutput"),
        node("NVIDIA Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2, [3560, 320], {
            "model": {"__rl": True, "value": PRIMARY_MODEL, "mode": "id"},
            "options": {"temperature": 0, "timeout": 120000, "maxRetries": 1, "reasoningEffort": "low"},
        }, credentials=NVIDIA_CRED),
        node("Fallback Extractor", "@n8n/n8n-nodes-langchain.informationExtractor", 1.2, [3820, 300], {
            "text": "={{ $('Split Into Chunks').item.json.invoice_text }}",
            "schemaType": "manual",
            "inputSchema": json.dumps(INVOICE_SCHEMA, indent=2),
            "options": {"systemPromptTemplate": SYSTEM_PROMPT},
        }, onError="continueRegularOutput"),  # a failed part is turned into { error } by Merge Chunks
        node("Fallback Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2, [3820, 520], {
            "model": {"__rl": True, "value": FALLBACK_MODEL, "mode": "id"},
            "options": {"temperature": 0, "timeout": 60000, "maxRetries": 2},
        }, credentials=NVIDIA_CRED),
        node("Collect Results", "n8n-nodes-base.merge", 3, [4060, 100]),
        node("Merge Chunks", "n8n-nodes-base.code", 2, [4280, 100], {"jsCode": MERGE_JS}),
        node("Error Result", "n8n-nodes-base.code", 2, [4500, 420], {"jsCode": ERROR_JS}),
        node("Arithmetic Check", "n8n-nodes-base.code", 2, [4500, 100],
             {"mode": "runOnceForEachItem", "jsCode": CHECK_JS}),
    ]

    connections = {
        "Manual Trigger": main_link(["Invoice Input"]),
        "When Called by Orchestrator": main_link(["Invoice Input"]),
        "Invoice Input": main_link(["Read Invoice File"]),
        "Read Invoice File": main_link(["Check File Found"]),
        "Check File Found": main_link(["Extract PDF Text"], ["Error Result"]),
        "Extract PDF Text": main_link(["Detect Text Layer"]),
        "Detect Text Layer": main_link(["Has Text Layer?"]),
        "Has Text Layer?": main_link(["Native Text"], ["LlamaParse Upload"]),
        "Native Text": main_link(["Normalize Numbers"]),
        "LlamaParse Upload": main_link(["Wait 3s"], ["Error Result"]),
        "Wait 3s": main_link(["LlamaParse Job Status"]),
        "LlamaParse Job Status": main_link(["Check Job Status"], ["Error Result"]),
        "Check Job Status": main_link(["Job Done?"], ["Error Result"]),
        "Job Done?": main_link(["LlamaParse Markdown"], ["Wait 3s"]),
        "LlamaParse Markdown": main_link(["OCR Text"], ["Error Result"]),
        "OCR Text": main_link(["Normalize Numbers"]),
        "Normalize Numbers": main_link(["Split Into Chunks"]),
        "Split Into Chunks": main_link(["Information Extractor"]),
        "Information Extractor": main_link(["Collect Results"], ["Fallback Extractor"]),
        "Fallback Extractor": {"main": [[{"node": "Collect Results", "type": "main", "index": 1}]]},
        "Collect Results": main_link(["Merge Chunks"]),
        "Merge Chunks": main_link(["Arithmetic Check"]),
        "NVIDIA Chat Model": {"ai_languageModel": [[
            {"node": "Information Extractor", "type": "ai_languageModel", "index": 0}]]},
        "Fallback Chat Model": {"ai_languageModel": [[
            {"node": "Fallback Extractor", "type": "ai_languageModel", "index": 0}]]},
    }

    workflow = {
        "id": "InvParserAgent03",
        "name": "03_Invoice_Parser_Agent",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "pinData": {},
        "active": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print("wrote", build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE))
