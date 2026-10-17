"""Build workflows/03_Invoice_Parser_Agent.json (importable n8n workflow).

Merged version (Fedi + Omar): the teammate's agent (rich invoice schema, grounding check, chunking, fallback LLM,
needs_review) + Fedi's additions (binary or path input, prompt-technique switch with Few-Shot default,
Self-Consistency vote, x1000/x100 misread correction, fraud signals, LlamaParse credential, fixed number normalizer).

Flow: input (file sent by the caller, or a path under /data) -> read file if needed (error if missing) -> native PDF text extraction
  -> usable text layer (PDF with >= 2 amounts in its text)?
       yes -> use native text
       no  -> LlamaParse OCR v2 (upload -> poll status -> fetch markdown); also handles JPG/PNG
  -> Normalize Numbers (every amount -> plain number with dot decimal, EN/FR/TND formats)
  -> Split Into Chunks (long invoices: ~1500-char parts cut between rows)
  -> Prompt Technique (zero_shot | few_shot | cot | self_consistency; one item per part and per reading)
  -> Information Extractor (NVIDIA, one call per item)
       on error -> Fallback Extractor for that part: Groq (other provider) if a "Groq" credential
                   exists in n8n, otherwise the same fast NVIDIA model with the short zero-shot prompt
  -> Merge Chunks (Self-Consistency vote per part, then one invoice JSON)
  -> Arithmetic Check (Code): x1000 misread fix, quantity-glued-to-price fix, grounding, arithmetic, fraud signals
       status ok | arithmetic_mismatch | needs_review

Usage: python scripts/build_invoice_workflow.py [default_file_path]
Env: INV_PRIMARY_MODEL / INV_FALLBACK_MODEL override the model ids (e.g. an invalid primary forces the fallback).

Credentials are looked up BY NAME in the local n8n database (ids differ on every machine), so each
teammate gets a workflow wired to their own credentials. Names expected in n8n:
  NVIDIA_NIM_Free  (OpenAI type, base URL https://integrate.api.nvidia.com/v1)   required
  Groq             (OpenAI type, base URL https://api.groq.com/openai/v1)        optional fallback
  LlamaParse API   (Header Auth: name Authorization, value "Bearer llx-...")      optional; else $env.LLAMA_CLOUD_API_KEY
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "workflows" / "03_Invoice_Parser_Agent.json"
LLAMA = "https://api.cloud.llamaindex.ai/api/v2/parse"  # v1 is disabled for new accounts
LLAMA_CONFIG = '{"tier": "cost_effective", "version": "latest"}'
DEFAULT_FILE = "/data/invoices/INV-001.pdf"
AUTH = {"parameters": [{"name": "Authorization", "value": "=Bearer {{ $env.LLAMA_CLOUD_API_KEY }}"}]}
DEFAULT_TECHNIQUE = os.environ.get("INV_TECHNIQUE", "few_shot")  # best in the prompt evaluation
N8N_DB = OUT.parent.parent / "n8n_data" / "database.sqlite"


def credential(name, type_="openAiApi"):
    """n8n credential reference {type: {id, name}} for the credential with this name, or None."""
    try:
        db = sqlite3.connect(f"file:{N8N_DB.as_posix()}?mode=ro", uri=True)
        row = db.execute("select id from credentials_entity where name = ? and type = ?", (name, type_)).fetchone()
    except sqlite3.Error:
        row = None
    return {type_: {"id": row[0], "name": name}} if row else None


NVIDIA_CRED = credential("NVIDIA_NIM_Free") or {"openAiApi": {"id": "SPONP3X9OugaVEBi", "name": "NVIDIA_NIM_Free"}}
GROQ_CRED = credential("Groq")
LLAMA_CRED = credential("LlamaParse API", "httpHeaderAuth")
# Primary model: the fastest one that passed the 26-invoice prompt evaluation (median ~28 s per invoice).
PRIMARY_MODEL = os.environ.get("INV_PRIMARY_MODEL", "meta/llama-3.2-11b-vision-instruct")
# Fallback: Groq (another provider) if a "Groq" credential exists; otherwise the same fast NVIDIA model with the
# short zero-shot prompt (nemotron-120b, the previous fallback, timed out on the free tier). A part the primary
# could not read (timeout, invalid JSON) is retried once this way.
FALLBACK_CRED = GROQ_CRED or NVIDIA_CRED
FALLBACK_MODEL = os.environ.get("INV_FALLBACK_MODEL", "llama-3.3-70b-versatile" if GROQ_CRED else PRIMARY_MODEL)
MAX_TOKENS = 2000  # one part's JSON is ~300-1200 tokens: a model stuck repeating itself stops here instead of timing out
CHUNK_CHARS = 900  # smaller parts = shorter answers: long invoices no longer time out on the free tier

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

INVOICE_SCHEMA = {**INVOICE_SCHEMA, "properties": {
    "reasoning": {"type": "string", "description": "Chain-of-Thought only: one line per printed amount. Omit otherwise."},
    **INVOICE_SCHEMA["properties"]}}

SYSTEM_PROMPT = """You extract data from documents submitted as vehicle repair invoices for an insurance claims system.
Rules:
- Copy every number EXACTLY as printed, even if it looks wrong. Never recompute, fix or infer amounts: a separate step checks the arithmetic.
- Amounts are already normalized to a dot decimal separator ("1 190.500" means 1190.5); spaces inside a number are thousands separators only within the same table cell. Output plain JSON numbers.
- If a value is not printed, omit the field (never write 0 for it). Never invent a quantity or unit price.
- If labor appears as a row of the items table, keep it as a line item with category "labor" and do not fill the labor object.
- Put stamp duty (timbre fiscal) and other fees added after tax in other_charges, not in line_items.
- Set is_invoice to false if the document is not an invoice (letter, quote/devis, report, form).
- The text may be one part of a longer invoice: extract only what is printed in that part, and omit header or total fields that are not in it.
- Write invoice_date as YYYY-MM-DD. A date printed as dd/mm/yyyy is day first: 05/10/2026 means 2026-10-05."""

FEW_SHOT_EXAMPLES = """

Two examples (text, then the JSON to return). Return ONE JSON object for the document you are given, then stop.

Example 1:
  AUTO PLUS GARAGE | Invoice No: INV-5521 | Date: 2026-08-14
  Rear bumper  1  380.00  380.00
  Paint (rear)  1  95.00  95.00
  Labor (4 h x 35.00)  140.00
  Subtotal 615.00 | VAT 19% (base 475.00) 90.25 | VAT 7% (base 140.00) 9.80 | TOTAL (TND) 715.05
{"is_invoice":true,"invoice_number":"INV-5521","garage_name":"AUTO PLUS GARAGE","invoice_date":"2026-08-14","currency":"TND","line_items":[{"description":"Rear bumper","category":"part","quantity":1,"unit_price":380,"line_total":380},{"description":"Paint (rear)","category":"paint","quantity":1,"unit_price":95,"line_total":95},{"description":"Labor (4 h x 35.00)","category":"labor","quantity":4,"unit_price":35,"line_total":140}],"subtotal":615,"tax_lines":[{"label":"VAT 19%","rate":19,"base":475,"amount":90.25},{"label":"VAT 7%","rate":7,"base":140,"amount":9.8}],"total":715.05}

Example 2 (columns: Désignation Qté P.U. Remise Montant):
  Garage Martin | Facture N° F-2207 | Date : 21/07/2026
  Rétroviseur gauche  1  250.00  10%  225.00
  Main d'oeuvre  2  40.00  80.00
  Sous-total 305.00 | Remise -25.00 | Total HT 280.00 | TVA 19% 53.20 | Timbre fiscal 1.00 | NET A PAYER (TND) 334.20
{"is_invoice":true,"invoice_number":"F-2207","garage_name":"Garage Martin","invoice_date":"2026-07-21","currency":"TND","line_items":[{"description":"Rétroviseur gauche","category":"part","quantity":1,"unit_price":250,"discount_percent":10,"line_total":225},{"description":"Main d'oeuvre","category":"labor","quantity":2,"unit_price":40,"line_total":80}],"subtotal":305,"discount_total":25,"net_before_tax":280,"vat_rate":19,"vat":53.2,"other_charges":[{"label":"Timbre fiscal","amount":1}],"total":334.2}

In both examples the number right after the item name is the quantity, not part of the price. Every line item uses
the same fields (description, category, quantity, unit_price, line_total), labor rows included. Fields that are not
printed (no discount, no labor object, no Total HT) are left out, never written as 0. When several VAT rates are
printed, put one entry per rate in tax_lines and leave vat and vat_rate out. A discount is a positive number.
Never copy the examples: their invoice numbers, garages and items must never appear in your answer."""

COT_INSTRUCTIONS = """

Think step by step before answering. Fill the "reasoning" field FIRST, then the other fields:
- In "reasoning", write one short line per amount printed on the invoice: <printed label>: "<amount as printed>" -> <JSON field> = <number>
  Example: Total HT: "280.00" -> net_before_tax = 280
  Example: Rétroviseur gauche, Remise 10%: "225.00" -> line_items[0].line_total = 225, discount_percent = 10
- Then fill every other field using ONLY the numbers you wrote in "reasoning". Keep "reasoning" to these lines."""

PROMPTS = {"zero_shot": SYSTEM_PROMPT, "few_shot": SYSTEM_PROMPT + FEW_SHOT_EXAMPLES, "cot": SYSTEM_PROMPT + COT_INSTRUCTIONS}

INPUT_JS = r"""// The invoice can arrive two ways (both work, the orchestrator uses either):
//  - as a file sent by the caller (binary data, any field name: PDF, JPG or PNG)
//  - as a path under /data: file_path, invoice_path or claim.invoice_path
// The claim (claimed_amount, incident_date) is kept for the fraud signals in Arithmetic Check.
const item = $input.first();
const j = item.json || {};
const claim = j.claim || j;
const technique = j.technique || null;            // optional: the evaluation workflow sets it per run
const bin = item.binary || {};
const keys = Object.keys(bin);
const isDoc = (k) => /pdf|image\//i.test(bin[k].mimeType || '') || /\.(pdf|png|jpe?g)$/i.test(bin[k].fileName || '');
const key = ['invoice', 'data'].find((k) => bin[k]) || keys.find(isDoc) || keys[0];
if (key) {
  return [{ json: { has_file: true, file_path: bin[key].fileName || 'uploaded file', claim, technique },
            binary: { data: bin[key] } }];
}
const path = j.file_path || j.invoice_path || claim.invoice_path || '__DEFAULT_FILE__';
return [{ json: { has_file: false, file_path: path, claim, technique } }];"""

TECHNIQUE_JS = r"""// ===== PROMPT TECHNIQUE ======================================================================
// Which prompt-engineering technique the agent uses (compared on 26 labelled invoices: Few-Shot was best).
//   zero_shot | few_shot | cot | self_consistency
// The orchestrator gets DEFAULT_TECHNIQUE; the evaluation workflow overrides it per run with { technique }.
const DEFAULT_TECHNIQUE = '__DEFAULT_TECHNIQUE__';
const PROMPTS = __PROMPTS__;
const SETTINGS = {
  zero_shot:        { prompt: 'zero_shot', runs: 1, temperature: 0 },
  few_shot:         { prompt: 'few_shot',  runs: 1, temperature: 0 },
  cot:              { prompt: 'cot',       runs: 1, temperature: 0 },
  self_consistency: { prompt: 'zero_shot', runs: 3, temperature: 0.7 }, // 3 readings per part + vote in Merge Chunks
};
// ==============================================================================================
const requested = $('Invoice Input').first().json.technique;
const technique = SETTINGS[requested] ? requested : DEFAULT_TECHNIQUE;
const cfg = SETTINGS[technique];
const out = [];
$input.all().forEach((it, idx) => {
  for (let run = 0; run < cfg.runs; run++) {
    out.push({
      json: { ...it.json, technique, run, runs: cfg.runs, temperature: cfg.temperature, system_prompt: PROMPTS[cfg.prompt],
              fallback_prompt: PROMPTS.zero_shot },  // short prompt for the fallback model
      pairedItem: { item: idx },
    });
  }
});
return out;"""

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

NORMALIZE_JS = r"""// Amounts are rewritten as plain numbers with a dot decimal (thousands separators removed) before the LLM
// reads them, whatever the format: "1,850.450" (English), "1.602,037" or "1 602,037" (French), "450.000" (TND).
// Each number is handled on its own, so a document mixing formats cannot break another number.
// Decimals beyond 2 are trimmed when they are zeros ("450.000" -> "450.00") so the LLM never sees the
// ambiguous "x.000" form that it tends to read as thousands.
let text = String($json.invoice_text || '');
const tnd = /\b(TND|DT|dinars?)\b/i.test(text);
const english = /\d,\d{3}\.\d/.test(text);            // style hint for a lone "1,555"
const trim = (dec) => (dec.length > 2 ? dec.replace(/0+$/, '').padEnd(2, '0') : dec);
// 1. English with thousands: 1,850.450 -> 1850.45
text = text.replace(/(?<![\d.,])(\d{1,3}(?:,\d{3})+)\.(\d+)(?!\d)/g, (m, i, d) => `${i.replace(/,/g, '')}.${trim(d)}`);
// 2. French with dot thousands: 1.602,037 -> 1602.037
text = text.replace(/(?<![\d.,])(\d{1,3}(?:\.\d{3})+),(\d+)(?!\d)/g, (m, i, d) => `${i.replace(/\./g, '')}.${trim(d)}`);
// 3. Decimal comma: 346,250 -> 346.25 (spaces between groups are left: they may separate two table cells).
//    A lone "1,555" in an English document is a thousands separator.
text = text.replace(/(?<![\d,])(\d+),(\d{1,3})(?![\d,])/g, (m, i, d) => (english && d.length === 3 ? `${i}${d}` : `${i}.${trim(d)}`));
// 4. TND amounts always have 3 decimals: 450.000 -> 450.00
if (tnd) text = text.replace(/(?<![\d.,])(\d+)\.(\d{3})(?![\d.,])/g, (m, i, d) => `${i}.${trim(d)}`);
return { json: { ...$json, invoice_text: text, number_format: 'en' } };"""

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
// Self-Consistency: each part was read several times; the readings are combined field by field first.
// Header fields come from the first part that has them, totals from the last one.
// Which part and which reading each result belongs to. The Information Extractor does not tag its successful
// results with their input, so the mapping is rebuilt from what n8n does keep: the failed items are tagged
// (they went to the Fallback Extractor, in order) and the successful ones come out in input order.
const PT = $('Prompt Technique').all().map((it) => it.json);
const safeAll = (fn) => { try { return fn() || []; } catch (e) { return []; } };
const primaryOk = safeAll(() => $('Information Extractor').all(0));
const primaryErr = safeAll(() => $('Information Extractor').all(1));
const fallback = $('Fallback Extractor').isExecuted ? safeAll(() => $('Fallback Extractor').all()) : [];
const pIdx = (it, k) => (Array.isArray(it.pairedItem) ? it.pairedItem[0]?.item : it.pairedItem?.item) ?? k;
const failedIdx = primaryErr.map(pIdx);
const okIdx = PT.map((_, i) => i).filter((i) => !failedIdx.includes(i));
let reads = [
  ...primaryOk.map((it, k) => ({ idx: okIdx[k], out: it.json.output, error: it.json.error })),
  ...fallback.map((it, k) => ({ idx: failedIdx[k], out: it.json.output, error: it.json.error })),
];
if (reads.length !== PT.length) {   // unexpected shape: fall back to the merged input, in order
  reads = $input.all().map((it, k) => ({ idx: k, out: it.json.output, error: it.json.error }));
}
reads = reads.map((r) => ({ ...r, chunk_index: PT[r.idx]?.chunk_index ?? r.idx, run: PT[r.idx]?.run ?? 0 }));
// Few-Shot leakage guard: a reading that contains the prompt examples (their invoice numbers, garages or items)
// while the invoice text does not is a copy of the example, not a reading. It counts as failed, never as data.
const EXAMPLE_MARKS = ['INV-5521', 'F-2207', 'AUTO PLUS GARAGE', 'Garage Martin', 'Rétroviseur gauche', 'Paint (rear)'];
for (const r of reads) {
  if (!r.out || r.error) continue;
  const text = String(PT[r.idx]?.invoice_text || '').toLowerCase();
  const copied = EXAMPLE_MARKS.filter((m) => JSON.stringify(r.out).toLowerCase().includes(m.toLowerCase()) && !text.includes(m.toLowerCase()));
  if (copied.length) r.error = `the model copied the prompt example (${copied.join(', ')})`;
}
const items = reads;
const cfg = $('Prompt Technique').first().json;

// ---- vote helpers
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const key = (v) => JSON.stringify(v ?? null);
const mode = (vals) => { const c = {}; let best = null, n = 0;
  for (const v of vals) { const k = key(v); c[k] = (c[k] || 0) + 1; if (c[k] > n) { n = c[k]; best = v ?? null; } } return best; };
// numbers: the value most readings agree on; otherwise the middle reading (odd count) or the tie-breaker's value
const voteNum = (vals, tb) => {
  const valid = vals.map(num).filter((v) => v !== null);
  if (valid.length * 2 <= vals.length) return undefined;
  const c = {}; for (const v of valid) c[v] = (c[v] || 0) + 1;
  const top = Object.entries(c).sort((a, b) => b[1] - a[1])[0];
  if (top[1] * 2 > valid.length) return Number(top[0]);
  if (valid.length % 2) return [...valid].sort((a, b) => a - b)[Math.floor(valid.length / 2)];
  return num(vals[tb]) ?? valid[0];
};
const same = (vals) => vals.every((v) => key(v) === key(vals[0]));
function vote(outs) {
  if (outs.length === 1) return { out: outs[0], agree: null };
  const res = {}; let agreeN = 0, totalN = 0;
  const NUMS = ['subtotal', 'discount_total', 'net_before_tax', 'vat_rate', 'vat', 'total'];
  for (const k of ['is_invoice', 'invoice_number', 'garage_name', 'invoice_date', 'vehicle_plate', 'claim_ref', 'currency', 'prices_include_tax']) {
    const vals = outs.map((o) => o[k]); const v = mode(vals); if (v !== null && v !== undefined) res[k] = v; totalN++; if (same(vals)) agreeN++;
  }
  for (const k of NUMS) {
    const vals = outs.map((o) => o[k]); const v = voteNum(vals, 0); if (v !== undefined) res[k] = v; totalN++; if (same(vals.map(num))) agreeN++;
  }
  // representative reading (tie-breaker, and source of tax_lines / other_charges / labor): agrees most with the vote
  const score = (o) => NUMS.filter((k) => num(o[k]) !== null && num(o[k]) === res[k]).length;
  const repIdx = outs.reduce((b, o, i) => (score(o) > score(outs[b]) ? i : b), 0);
  for (const k of ['tax_lines', 'other_charges', 'labor']) if (outs[repIdx][k] !== undefined) res[k] = outs[repIdx][k];
  const counts = outs.map((o) => (o.line_items || []).length);
  const n = mode(counts); totalN++; if (same(counts)) agreeN++;
  const pool = outs.filter((o) => (o.line_items || []).length === n);
  const tb = Math.max(0, pool.indexOf(outs[repIdx]));
  res.line_items = Array.from({ length: n }, (_, i) => {
    const rows = pool.map((o) => o.line_items[i]); const li = {};
    for (const k of ['description', 'category']) { const vals = rows.map((r) => r[k]); const v = mode(vals); if (v !== null) li[k] = v; totalN++; if (same(vals)) agreeN++; }
    for (const k of ['quantity', 'unit_price', 'discount_percent', 'discount_amount', 'vat_rate', 'line_total']) {
      const vals = rows.map((r) => r[k]); const v = voteNum(vals, tb); if (v !== undefined) li[k] = v;
      if (vals.some((x) => x !== undefined)) { totalN++; if (same(vals.map(num))) agreeN++; }
    }
    return li;
  });
  return { out: res, agree: agreeN / totalN };
}

// ---- group the readings by part and vote
const byChunk = {};
for (const r of reads) (byChunk[r.chunk_index] = byChunk[r.chunk_index] || []).push(r);
const parts = []; const agreements = []; let reasoning = null;
for (const idx of Object.keys(byChunk).map(Number).sort((a, b) => a - b)) {
  const ok = byChunk[idx].filter((r) => r.out && !r.error).sort((a, b) => a.run - b.run);
  if (!ok.length) {
    const e = byChunk[idx].find((r) => r.error)?.error;
    return [{ json: { error: `LLM extraction failed on primary and fallback models: ${e?.message ?? e ?? 'no output'}` } }];
  }
  const outs = ok.map((r) => { const { reasoning: why, ...rest } = r.out; if (why && reasoning === null) reasoning = why; return rest; });
  const v = vote(outs); parts.push(v.out); if (v.agree !== null) agreements.push(v.agree);
}

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
    extraction: {
      technique: cfg.technique, runs: cfg.runs, chunks: parts.length, llm_calls: PT.length + fallback.length,
      successful_reads: reads.filter((r) => r.out && !r.error).length,
      agreement: agreements.length ? Math.round((agreements.reduce((a, b) => a + b, 0) / agreements.length) * 1000) / 1000 : null,
      llm_fallback_used: $('Fallback Extractor').isExecuted,
      reasoning,
    },
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

CHECK_JS = r"""// Deterministic arithmetic check on the extracted invoice.
// status: ok | arithmetic_mismatch (+15 risk points) | needs_review (not an invoice, incomplete or
// amounts not found on the invoice, 0 points)
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
const total = (arr) => round(arr.reduce((s, x) => s + x, 0));

// A 0 the model wrote for an amount that is not printed (no discount, no labor, no Total HT) means "absent".
const dropZeros = (o, keys) => { for (const k of keys) if (o && o[k] === 0) delete o[k]; };
dropZeros(inv, ['subtotal', 'discount_total', 'net_before_tax', 'vat_rate', 'vat', 'total']);
if (inv.labor) {
  dropZeros(inv.labor, ['hours', 'rate', 'total']);
  if (!['hours', 'rate', 'total'].some((k) => num(inv.labor[k]) != null)) delete inv.labor;
}
for (const li of inv.line_items || []) dropZeros(li, ['discount_percent', 'discount_amount', 'vat_rate']);
if (inv.other_charges) inv.other_charges = inv.other_charges.filter((c) => c.amount !== 0);

const issues = [];
const reviewReasons = [];
const uncheckedLines = [];
const items = inv.line_items || [];

// 0. Grounding: every amount the LLM returns must be printed in the invoice text. An amount that is not
// (recomputed, "fixed" or invented by the LLM) is not trusted: the checks that depend on it are skipped,
// so arithmetic_issue only quotes numbers that are really printed on the invoice.
const source = $('Normalize Numbers').first().json;
const printedValues = [];
for (const token of String(source.invoice_text || '').match(/\d[\d \u00a0\u202f,]*(?:\.\d+)?/g) || []) {
  const parts = (source.number_format === 'en' ? token.replace(/,/g, '') : token)
    .split(/[ \u00a0\u202f,]+/).filter(Boolean).slice(0, 8);
  // "1 043.20" may be one amount or two columns: keep every contiguous grouping
  for (let i = 0; i < parts.length; i++) {
    for (let j = i + 1; j <= parts.length; j++) printedValues.push(parseFloat(parts.slice(i, j).join('')));
  }
}
const isPrinted = (n) => printedValues.some((p) => Math.abs(p - Math.abs(n)) < 0.006);
const corrected = [];
// 0a. Quantity glued to the price: a table row "Calandre 1 189.90 189.90" can be read as unit price 1189.9
// (a space is also a French thousands separator). If a price starts with the line's quantity followed by
// 3 digits and the rest is printed, the rest is tried; it is kept when it makes the line add up, or, for lines
// that add up both ways, when it makes the sum of the lines match the printed subtotal.
const fitsLine = (li, u, lt) => {
  const q = num(li.quantity);
  if (q == null || u == null || lt == null) return false;
  const c = [q * u - (num(li.discount_amount) ?? 0), q * u];
  if (num(li.discount_percent) != null) c.push(q * u * (1 - pct(li.discount_percent)));
  return c.some((x) => close(x, lt));
};
const unglue = (n, q) => {
  if (n == null || !Number.isInteger(q) || q <= 0) return null;
  const s = String(Math.trunc(n));
  if (s.length !== String(q).length + 3 || !s.startsWith(String(q))) return null;
  const r = round(n - q * 1000);
  return r > 0 && isPrinted(r) ? r : null;
};
const setLine = (li, u, lt) => {
  const label = `"${li.description}" (quantity read as part of the price)`;
  if (u !== li.unit_price) { corrected.push({ field: `unit_price ${label}`, from: li.unit_price, to: u }); li.unit_price = u; }
  if (lt !== li.line_total) { corrected.push({ field: `line_total ${label}`, from: li.line_total, to: lt }); li.line_total = lt; }
};
const ambiguous = [];
for (const li of items) {
  const q = num(li.quantity), u = num(li.unit_price), lt = num(li.line_total);
  const uu = unglue(u, q), lu = unglue(lt, q);
  if (uu == null) continue;
  if (!isPrinted(u)) { setLine(li, uu, lu != null && !isPrinted(lt) ? lu : lt); continue; } // glued value not on the invoice
  const options = [[uu, lt], ...(lu != null ? [[uu, lu]] : [])].filter(([a, b]) => fitsLine(li, a, b));
  if (!options.length) continue;
  if (!fitsLine(li, u, lt)) setLine(li, ...options[0]);
  else if (lu != null && options.some(([a, b]) => b === lu)) ambiguous.push({ li, alt: [uu, lu] });
}
if (ambiguous.length && ambiguous.length <= 4) {
  const laborOut = items.some((li) => li.category === 'labor') ? 0 : num(inv.labor?.total) ?? 0;
  const targets = [inv.subtotal, inv.net_before_tax].map(num).filter((x) => x != null);
  const sumWith = (mask) => round(items.reduce((s, li) => {
    const k = ambiguous.findIndex((a) => a.li === li);
    return s + ((k >= 0 && mask & (1 << k) ? ambiguous[k].alt[1] : num(li.line_total)) ?? 0);
  }, laborOut));
  const matches = (mask) => targets.some((t) => close(sumWith(mask), t));
  if (targets.length && !matches(0)) {
    for (let mask = 1; mask < 1 << ambiguous.length; mask++) {
      if (matches(mask)) { ambiguous.forEach((a, k) => mask & (1 << k) && setLine(a.li, ...a.alt)); break; }
    }
  }
}

// 0b. x1000 / x100 misreads (a model reading "450.000" as 450000): an amount that is not printed but whose
// /1000 or /100 is printed is corrected, amount by amount, before any check (listed in extraction.corrected_amounts).
const fix = (obj, k, label) => {
  const n = num(obj?.[k]);
  if (n == null || n === 0 || isPrinted(n)) return;
  for (const f of [1000, 100]) if (isPrinted(n / f)) { obj[k] = round(n / f); corrected.push({ field: label, from: n, to: obj[k] }); return; }
};
for (const k of ['subtotal', 'discount_total', 'net_before_tax', 'vat', 'total']) fix(inv, k, k);
for (const li of items) for (const k of ['unit_price', 'discount_amount', 'line_total']) fix(li, k, `${k} "${li.description}"`);
if (inv.labor) for (const k of ['rate', 'total']) fix(inv.labor, k, `labor.${k}`);
for (const t of inv.tax_lines || []) for (const k of ['base', 'amount']) fix(t, k, `tax ${k} "${t.label}"`);
for (const c of inv.other_charges || []) fix(c, 'amount', `charge "${c.label}"`);

const ungrounded = [];
const UNTRUSTED = 'untrusted';
const ok = (x) => typeof x === 'number';
const g = (v, field) => {
  const n = num(v);
  if (n == null) return null;
  if (printedValues.some((p) => Math.abs(p - Math.abs(n)) < 0.006)) return n;
  ungrounded.push({ field, value: n });
  return UNTRUSTED;
};

if (inv.is_invoice === false) reviewReasons.push('not_an_invoice');
if (!items.length) reviewReasons.push('no_line_items');

// 1. Each line: quantity x unit price, minus its discount
let linesTrusted = true;
const lineTotals = [];
for (const li of items) {
  const printed = g(li.line_total, `line_total "${li.description}"`);
  if (printed === null) { reviewReasons.push(`line_without_amount: ${li.description}`); linesTrusted = false; continue; }
  if (printed === UNTRUSTED) { linesTrusted = false; continue; }
  lineTotals.push(printed);
  const qty = num(li.quantity);
  const price = g(li.unit_price, `unit_price "${li.description}"`);
  if (qty == null || !ok(price)) { uncheckedLines.push(li.description); continue; }
  const gross = qty * price;
  const candidates = [gross - (num(li.discount_amount) ?? 0)];
  if (num(li.discount_percent) != null) candidates.push(gross * (1 - pct(li.discount_percent)));
  if (!candidates.some((c) => close(c, printed))) {
    issues.push({ type: 'line_total_mismatch', item: li.description, printed, expected: round(candidates.at(-1)) });
  }
}

// 2. Labor printed outside the table (ignored if the same amount is also a "labor" line)
const hasLaborLine = items.some((li) => li.category === 'labor');
const laborRaw = g(inv.labor?.total, 'labor.total');
let laborTotal = ok(laborRaw) ? laborRaw : 0;
if (laborRaw === UNTRUSTED && !hasLaborLine) linesTrusted = false;
const laborRate = g(inv.labor?.rate, 'labor.rate');
if (ok(laborRaw) && ok(laborRate) && num(inv.labor?.hours) != null && !close(inv.labor.hours * laborRate, laborRaw)) {
  issues.push({ type: 'labor_mismatch', printed: laborRaw, expected: round(inv.labor.hours * laborRate) });
}
if (items.some((li) => li.category === 'labor' && close(num(li.line_total) ?? 0, laborTotal))) laborTotal = 0;

// 3. Subtotal, discount, net before tax
const linesSum = linesTrusted ? total([...lineTotals, laborTotal]) : null;
const discountRaw = g(inv.discount_total, 'discount_total');
const discount = ok(discountRaw) ? Math.abs(discountRaw) : 0;   // "Remise -60.00" read as -60 is still a 60 discount
const discountKnown = discountRaw !== UNTRUSTED;
let base = linesSum != null && discountKnown ? linesSum - discount : null;
const subtotal = g(inv.subtotal, 'subtotal');
if (ok(subtotal)) {
  if (linesSum != null && close(subtotal, linesSum)) base = discountKnown ? subtotal - discount : null;
  else if (linesSum != null && discount && close(subtotal, linesSum - discount)) base = subtotal;
  else {
    if (linesSum != null) issues.push({ type: 'subtotal_mismatch', printed: subtotal, expected: linesSum });
    base = discountKnown ? subtotal - discount : null;
  }
}
const net = g(inv.net_before_tax, 'net_before_tax');
if (ok(net)) {
  if (base != null && !close(net, base)) issues.push({ type: 'net_before_tax_mismatch', printed: net, expected: round(base) });
  base = net;
}

// 4. Taxes (one rate or several); with tax-inclusive prices the tax is informative only
const taxLines = (inv.tax_lines || []).map((t) => ({
  label: t.label, rate: num(t.rate), base: g(t.base, `tax base "${t.label}"`), amount: g(t.amount, `tax "${t.label}"`),
}));
// The tax may be computed on a tax-exclusive base (base x rate) or contained in a tax-inclusive one
// ("dont TVA": base - base / (1 + rate)).
const taxFits = (b, r, amount) => close(b * pct(r), amount) || close(b - b / (1 + pct(r)), amount);
for (const t of taxLines) {
  if (t.rate != null && ok(t.base) && ok(t.amount) && !taxFits(t.base, t.rate, t.amount)) {
    issues.push({ type: 'tax_line_mismatch', label: t.label, printed: t.amount, expected: round(t.base * pct(t.rate)) });
  }
}
const vat = g(inv.vat, 'vat');
// Several VAT rates printed ("TVA 19% ... TVA 7% ...") but fewer extracted: the tax total is unknown, so the VAT
// and grand-total checks are skipped and the claim goes to human review instead of being flagged.
const printedRates = new Set([...String(source.invoice_text || '').matchAll(/\b(?:TVA|VAT)\s*(\d{1,2}(?:\.\d+)?)\s*%/gi)].map((m) => Number(m[1])));
const extractedRates = new Set(taxLines.length ? taxLines.map((t) => t.rate) : [num(inv.vat_rate)].filter((x) => x != null));
const taxIncomplete = printedRates.size >= 2 && extractedRates.size < printedRates.size;
if (taxIncomplete) reviewReasons.push('tax_rates_incomplete');
if (!inv.prices_include_tax && base != null) {
  if (taxLines.length && taxLines.every((t) => ok(t.base)) && !close(total(taxLines.map((t) => t.base)), base)) {
    issues.push({ type: 'tax_base_mismatch', printed: total(taxLines.map((t) => t.base)), expected: round(base) });
  }
  if (!taxLines.length && !taxIncomplete && ok(vat) && num(inv.vat_rate) != null && !taxFits(base, inv.vat_rate, vat)) {
    issues.push({ type: 'vat_mismatch', printed: vat, expected: round(base * pct(inv.vat_rate)) });
  }
}
const tax = taxIncomplete ? null : taxLines.length
  ? (taxLines.every((t) => ok(t.amount)) ? total(taxLines.map((t) => t.amount)) : null)
  : (vat === UNTRUSTED ? null : vat ?? 0);

// 5. Grand total = net + tax + other charges (timbre fiscal...). Both the tax-exclusive and the
// tax-inclusive readings are accepted, so a wrong prices_include_tax flag from the LLM is not a fraud signal.
const chargeValues = (inv.other_charges || []).map((c) => g(c.amount, `charge "${c.label}"`));
const charges = chargeValues.includes(UNTRUSTED) ? null : total(chargeValues.filter(ok));
const grandTotal = g(inv.total, 'total');
if (grandTotal === null) reviewReasons.push('no_total');
const known = base != null && tax != null && charges != null;
const totals = known ? [round(base + tax + charges), round(base + charges)] : [];
const expectedTotal = known ? (inv.prices_include_tax ? totals[1] : totals[0]) : null;
if (ok(grandTotal) && known && !totals.some((t) => close(t, grandTotal))) {
  issues.push({ type: 'total_mismatch', printed: grandTotal, expected: expectedTotal });
}
if (ungrounded.length) reviewReasons.push('ungrounded_amounts');

// Arithmetic evidence found on printed numbers wins; otherwise any doubt means human review, never fraud.
const notReadable = reviewReasons.some((r) => r === 'not_an_invoice' || r === 'no_line_items');
const status = notReadable ? 'needs_review'
  : issues.length ? 'arithmetic_mismatch'
  : reviewReasons.length ? 'needs_review' : 'ok';

// Fraud signals for the decision agent (not arithmetic). They use the claim sent by the orchestrator.
const claim = $('Invoice Input').first().json.claim || {};
const warnings = [];
const claimed = typeof claim.claimed_amount === 'number' ? claim.claimed_amount : parseFloat(claim.claimed_amount);
const invTotal = num(inv.total);
let amountMatchesClaim = null;
if (Number.isFinite(claimed) && invTotal != null) {
  amountMatchesClaim = close(claimed, invTotal);
  if (!amountMatchesClaim) warnings.push(`Claimed amount ${claimed.toFixed(2)} differs from invoice total ${invTotal.toFixed(2)}`);
}
const iso = /^\d{4}-\d{2}-\d{2}$/;
if (iso.test(inv.invoice_date || '') && iso.test(claim.incident_date || '') && inv.invoice_date < claim.incident_date) {
  warnings.push(`Invoice dated ${inv.invoice_date}, before the incident (${claim.incident_date})`);
}
const seenLines = new Set();
for (const li of items) {
  const k = `${li.category || 'part'}|${String(li.description || '').trim().toLowerCase()}`;
  if (seenLines.has(k)) warnings.push(`"${li.description}" appears more than once`);
  seenLines.add(k);
}

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
// Paint, painting materials, fluids and consumables are "other" even when the invoice (or the model) calls them a part.
const NOT_A_PART = /\b(paint|painting|peinture|ingr[ée]dients?|consumables?|consommables?|fournitures?|coolant|antigel|liquide)\b/i;
const lineType = (li) => {
  const t = li.category ? TYPES[li.category] || 'other' : 'part';
  return t === 'part' && NOT_A_PART.test(li.description || '') ? 'other' : t;
};
const lineItems = items.map((li) => ({
  part: li.description,
  type: lineType(li),
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
    warnings,                       // fraud signals: claimed amount vs invoice, invoice before incident, duplicate line
    amount_matches_claim: amountMatchesClaim,
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
    ungrounded_amounts: ungrounded,
    extraction: { ...($json.extraction || {}), corrected_amounts: corrected },
  },
};"""


def llama_auth():
    """LlamaParse auth: the n8n credential "LlamaParse API" (Header Auth) when it exists, else $env.LLAMA_CLOUD_API_KEY."""
    if LLAMA_CRED:
        return {"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"}, {"credentials": LLAMA_CRED}
    return {"sendHeaders": True, "headerParameters": AUTH}, {}


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
        node("Invoice Input", "n8n-nodes-base.code", 2, [220, 100],
             {"jsCode": INPUT_JS.replace("__DEFAULT_FILE__", default_file)}),
        node("File Sent?", "n8n-nodes-base.if", 2.2, [330, 260], bool_if("={{ $json.has_file }}")),
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
            "method": "POST", "url": f"{LLAMA}/upload", **llama_auth()[0],
            "sendBody": True, "contentType": "multipart-form-data",
            "bodyParameters": {"parameters": [
                {"parameterType": "formBinaryData", "name": "file", "inputDataFieldName": "data"},
                {"name": "configuration", "value": LLAMA_CONFIG},
            ]},
            "options": {},
        }, onError="continueErrorOutput", **llama_auth()[1]),
        node("Wait 3s", "n8n-nodes-base.wait", 1.1, [1780, 260], {"amount": 3}, webhookId="inv-wait-3s"),
        node("LlamaParse Job Status", "n8n-nodes-base.httpRequest", 4.2, [2000, 260], {
            "url": f"={LLAMA}/{{{{ $('LlamaParse Upload').first().json.id }}}}", **llama_auth()[0], "options": {},
        }, onError="continueErrorOutput", **llama_auth()[1]),
        node("Check Job Status", "n8n-nodes-base.code", 2, [2220, 260],
             {"mode": "runOnceForEachItem", "jsCode": POLL_JS}, onError="continueErrorOutput"),
        node("Job Done?", "n8n-nodes-base.if", 2.2, [2440, 260], bool_if("={{ $json.done }}")),
        node("LlamaParse Markdown", "n8n-nodes-base.httpRequest", 4.2, [2660, 200], {
            "url": f"={LLAMA}/{{{{ $('LlamaParse Upload').first().json.id }}}}?expand=markdown_full", **llama_auth()[0],
            "options": {},
        }, onError="continueErrorOutput", **llama_auth()[1]),
        node("OCR Text", "n8n-nodes-base.set", 3.4, [2880, 200],
             set_fields({"invoice_text": "={{ $json.markdown_full }}", "extraction_method": "llamaparse_ocr"},
                        include_other=False)),
        node("Normalize Numbers", "n8n-nodes-base.code", 2, [3100, 100],
             {"mode": "runOnceForEachItem", "jsCode": NORMALIZE_JS}),
        node("Split Into Chunks", "n8n-nodes-base.code", 2, [3320, 100],
             {"jsCode": SPLIT_JS.replace("__CHUNK_CHARS__", str(CHUNK_CHARS))}),
        node("Prompt Technique", "n8n-nodes-base.code", 2, [3440, 260], {"jsCode": TECHNIQUE_JS
             .replace("__DEFAULT_TECHNIQUE__", DEFAULT_TECHNIQUE)
             .replace("__PROMPTS__", json.dumps(PROMPTS, ensure_ascii=False, indent=2))}),
        # Primary LLM. Errors (timeout, invalid JSON) go to the error output -> fallback, per part.
        node("Information Extractor", "@n8n/n8n-nodes-langchain.informationExtractor", 1.2, [3560, 100], {
            "text": "={{ $json.invoice_text }}",
            "schemaType": "manual",
            "inputSchema": json.dumps(INVOICE_SCHEMA, indent=2),
            "options": {"systemPromptTemplate": "={{ $json.system_prompt }}"},
        }, onError="continueErrorOutput"),
        node("NVIDIA Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2, [3560, 320], {
            "model": {"__rl": True, "value": PRIMARY_MODEL, "mode": "id"},
            "options": {"temperature": "={{ $json.temperature }}", "timeout": 90000, "maxRetries": 0, "maxTokens": MAX_TOKENS,
                        **({"reasoningEffort": "low"} if "gpt-oss" in PRIMARY_MODEL else {})},
        }, credentials=NVIDIA_CRED),
        node("Fallback Extractor", "@n8n/n8n-nodes-langchain.informationExtractor", 1.2, [3820, 300], {
            "text": "={{ $('Prompt Technique').item.json.invoice_text }}",
            "schemaType": "manual",
            "inputSchema": json.dumps(INVOICE_SCHEMA, indent=2),
            "options": {"systemPromptTemplate": "={{ $('Prompt Technique').item.json.fallback_prompt }}"},
        }, onError="continueRegularOutput"),  # a failed part is turned into { error } by Merge Chunks
        node("Fallback Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2, [3820, 520], {
            "model": {"__rl": True, "value": FALLBACK_MODEL, "mode": "id"},
            "options": {"temperature": 0, "timeout": 90000, "maxRetries": 1, "maxTokens": MAX_TOKENS},
        }, credentials=FALLBACK_CRED),
        node("Collect Results", "n8n-nodes-base.merge", 3, [4060, 100]),
        node("Merge Chunks", "n8n-nodes-base.code", 2, [4280, 100], {"jsCode": MERGE_JS}),
        node("Error Result", "n8n-nodes-base.code", 2, [4500, 420], {"jsCode": ERROR_JS}),
        node("Arithmetic Check", "n8n-nodes-base.code", 2, [4500, 100],
             {"mode": "runOnceForEachItem", "jsCode": CHECK_JS}),
    ]

    connections = {
        "Manual Trigger": main_link(["Invoice Input"]),
        "When Called by Orchestrator": main_link(["Invoice Input"]),
        "Invoice Input": main_link(["File Sent?"]),
        "File Sent?": main_link(["Check File Found"], ["Read Invoice File"]),
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
        "Split Into Chunks": main_link(["Prompt Technique"]),
        "Prompt Technique": main_link(["Information Extractor"]),
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
