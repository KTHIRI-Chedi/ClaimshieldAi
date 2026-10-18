"""Build the integrated ClaimShield AI workflows (orchestrator + agent copies) into integ/out/workflows.

Teammates' original files are never modified: each agent is copied and the integration changes are listed in
CHANGES (printed and written to INTEGRATION_CHANGES.md).

Workflow ids are fixed so the orchestrator's Execute Workflow nodes keep working after a CLI import:
  CSOrchestrator00  00_ClaimShield_Orchestrator
  CSIngestMotor01   01_Policy_Ingestion_Motor            (from Chedi's 01_Policy_Ingestion)
  CSPolicyRAG02     02_Policy_RAG_Agent                  (from Chedi's 02_Policy_RAG_Agent)
  CSVisualAgent03   03_Visual_Inspection_Agent           (Visual Inspection agent)
  InvParserAgent03  04_Invoice_Parser_Agent              (Fedi + Omar, unchanged)
  CSDecision05      05_Validation_Fraud_Decision_Agent   (Bahaeddine's 04_Validation_Fraud_Decision_Agent)
"""
import copy
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
OUT = HERE / "out" / "workflows"
DB = Path(os.environ.get("N8N_DB", "/tmp/claude-0/db4/database.sqlite"))
DATA = "/data/claimshield"
CHANGES = {}


def cred(name, type_, fallback_id):
    try:
        row = sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute(
            "select id, name from credentials_entity where name = ? and type = ?", (name, type_)).fetchone()
    except sqlite3.Error:
        row = None
    return {type_: {"id": row[0], "name": row[1]} if row else {"id": fallback_id, "name": name}}


def cred_by_type(type_, fallback_name, fallback_id):
    try:
        row = sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute(
            "select id, name from credentials_entity where type = ? order by updatedAt desc", (type_,)).fetchone()
    except sqlite3.Error:
        row = None
    return {type_: {"id": row[0], "name": row[1]} if row else {"id": fallback_id, "name": fallback_name}}


NVIDIA = cred("NVIDIA_NIM_Free", "openAiApi", "SPONP3X9OugaVEBi")
QDRANT = cred_by_type("qdrantApi", "Local_Qdrant", "DA9IF6z39EiJXHZ8")
GEMINI = cred_by_type("googlePalmApi", "Google Gemini(PaLM) Api account", "SET_GEMINI_CREDENTIAL")
SLACK = cred_by_type("slackApi", "Slack account", "SET_SLACK_CREDENTIAL")
LLAMA = cred("LlamaParse API", "httpHeaderAuth", "kPwMBFgYepTiwPR4")
WEBHOOK_AUTH = cred_by_type("httpHeaderAuth", "ClaimShield API key", "SET_API_KEY_CREDENTIAL") \
    if False else {"httpHeaderAuth": {"id": "SET_API_KEY_CREDENTIAL", "name": "ClaimShield API key"}}
GEMINI_MODEL = os.environ.get("CS_GEMINI_MODEL", "models/gemini-3.7-flash")   # Bahaeddine's decision model
EMBED_MODEL = "nvidia/nemotron-3-embed-1b"                                     # Chedi's embedding model
COLLECTION = "motor_policy_clauses"


def node(name, type_, version, pos, params=None, **extra):
    return {"parameters": params or {}, "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "cs/" + name)), "name": name,
            "type": type_, "typeVersion": version, "position": pos, **extra}


def link(*targets):
    return {"main": [[{"node": t, "type": "main", "index": 0} for t in br] for br in targets]}


def ai(type_, *targets):
    return {type_: [[{"node": t, "type": type_, "index": 0} for t in targets]]}


def sticky(name, text, pos, w=420, h=260, color=5):
    return node(name, "n8n-nodes-base.stickyNote", 1, pos, {"content": text, "width": w, "height": h, "color": color})


def workflow(id_, name, nodes, connections):
    return {"id": id_, "name": name, "nodes": nodes, "connections": connections, "active": False,
            "settings": {"executionOrder": "v1", "binaryMode": "separate"}, "pinData": {}, "meta": None,
            "versionId": str(uuid.uuid5(uuid.NAMESPACE_URL, "cs/version/" + id_)), "tags": []}


def save(w, filename):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / filename).write_text(json.dumps(w, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {filename}: {len(w['nodes'])} nodes")


def js(name):
    return (HERE / "js" / name).read_text(encoding="utf-8")


# ============================================================================ 05 Decision (Bahaeddine)
def build_decision():
    w = json.load(open(SRC / "04_Validation_Fraud_Decision_Agent.json", encoding="utf-8"))
    w["id"], w["name"] = "CSDecision05", "05_Validation_Fraud_Decision_Agent"
    byname = {n["name"]: n for n in w["nodes"]}
    log = CHANGES.setdefault("05_Validation_Fraud_Decision_Agent (Bahaeddine)", [])

    # 1. Airtable -> local CSV files (same columns as his airtable/*.csv)
    pol, prior = byname.pop("Find Policy"), byname.pop("Find Prior Claims")
    new = [
        node("Read Policies CSV", "n8n-nodes-base.readWriteFile", 1.1, pol["position"],
             {"fileSelector": f"{DATA}/policies.csv", "options": {}}, executeOnce=True),
        node("Parse Policies", "n8n-nodes-base.extractFromFile", 1.1, [pol["position"][0] + 112, pol["position"][1] + 160],
             {"operation": "csv", "options": {}}, alwaysOutputData=True),
        node("Read Claims History CSV", "n8n-nodes-base.readWriteFile", 1.1, prior["position"],
             {"fileSelector": f"{DATA}/claims_history.csv", "options": {}}, executeOnce=True),   # once, not once per policy row
        node("Parse Claims History", "n8n-nodes-base.extractFromFile", 1.1, [prior["position"][0] + 112, prior["position"][1] + 160],
             {"operation": "csv", "options": {}}, alwaysOutputData=True),
    ]
    lookup = byname["Policy Lookup"]["parameters"]
    code = lookup["jsCode"]
    code = code.replace("// Turns the Airtable results into the format Eligibility Check expects.",
                        "// Turns the policy and claim-history rows into the format Eligibility Check expects.\n"
                        "// [integration] rows come from /data/claimshield/policies.csv and claims_history.csv (same columns\n"
                        "// as the Airtable tables), so the system runs without an Airtable account.")
    code = code.replace("const found = $('Find Policy').all().map(i => row(i.json)).filter(r => r.policy_id);",
                        "const found = $('Parse Policies').all().map(i => row(i.json))\n"
                        "  .filter(r => r.policy_id && String(r.policy_id).trim() === String(claimItem.claim.policy_id).trim());")
    code = code.replace("const history = $('Find Prior Claims').all().map(i => row(i.json)).filter(r => r.incident_date);",
                        "const history = $('Parse Claims History').all().map(i => row(i.json))\n"
                        "  .filter(r => r.incident_date && String(r.policy_id).trim() === String(claimItem.claim.policy_id).trim());")
    assert "$('Parse Policies')" in code and "$('Parse Claims History')" in code
    lookup["jsCode"] = code
    log.append("Policies and claim history read from local CSV files (data/claimshield/*.csv) instead of Airtable: "
               "Find Policy / Find Prior Claims replaced by Read + Extract From File nodes, Policy Lookup filters by policy_id.")

    # 2. Rule Score: FR/EN part names, only real parts, invoice review flags
    rs = byname["Rule Score"]["parameters"]
    code = rs["jsCode"]
    old_parts = """  const seen = (v.damaged_parts || []).map(norm);
  const notVisible = (inv.line_items || [])
    .filter(li => li.part && li.type !== 'labor')
    .filter(li => {
      const p = norm(li.part);
      return !seen.some(s => s.includes(p) || p.includes(s));
    })
    .map(li => li.part);"""
    assert old_parts in code
    code = code.replace(old_parts, js("rule_parts.js").rstrip())
    old_ret = "      missing_inputs,\n    },"
    assert old_ret in code
    code = code.replace(old_ret, "      missing_inputs,\n      review_flags,\n    },")
    old_inv = "  const inv = invoice && !invoice.error ? invoice : {};"
    assert old_inv in code
    code = code.replace(old_inv, old_inv + """
  // [integration] the invoice agent can return status needs_review (amounts it could not verify) and fraud
  // warnings (claimed amount vs invoice total, invoice dated before the incident, duplicate line): they add no
  // points but always send the claim to a human.
  const review_flags = [];
  if (inv.status === 'needs_review') review_flags.push(`Invoice could not be fully verified (${(inv.review_reasons || []).join(', ') || 'needs review'})`);
  for (const w of inv.warnings || []) review_flags.push(`Invoice: ${w}`);""")
    rs["jsCode"] = code
    log.append("Rule Score: French (visual agent) and English (invoices) part names are mapped to one canonical name "
               "before the PART_NOT_VISIBLE check; only lines of type 'part' are compared (paint/consumables are 'other').")
    log.append("Rule Score: invoice status needs_review and invoice warnings are passed as review_flags (0 points).")

    dr = byname["Decide Route"]["parameters"]
    code = dr["jsCode"]
    anchor = "    if (llm_error) route_reasons.push('LLM assessment failed');"
    assert anchor in code
    code = code.replace(anchor, anchor + "\n    for (const f of base.review_flags || []) route_reasons.push(f);   // [integration]")
    old = "      missing_inputs: base.missing_inputs,"
    code = code.replace(old, old + "\n      review_flags: base.review_flags || [],")
    dr["jsCode"] = code
    log.append("Decide Route: review_flags are route reasons, so such a claim goes to human_review instead of auto_approve.")

    gm = byname["Google Gemini Chat Model"]
    gm["credentials"] = GEMINI
    log.append("Gemini credential re-pointed to Fedi's own Gemini key (model unchanged).")

    nodes = list(byname.values()) + new
    c = w["connections"]
    c.pop("Find Policy", None); c.pop("Find Prior Claims", None)
    c["Check Required Fields"] = link(["Read Policies CSV"])
    c["Read Policies CSV"] = link(["Parse Policies"])
    c["Parse Policies"] = link(["Read Claims History CSV"])
    c["Read Claims History CSV"] = link(["Parse Claims History"])
    c["Parse Claims History"] = link(["Policy Lookup"])
    for n in nodes:
        if n["name"] == "About":
            n["parameters"]["content"] += ("\n\n**Integration copy** (ClaimShield orchestrator): policies and claim history "
                                           "come from `data/claimshield/*.csv`; see INTEGRATION_CHANGES.md.")
    w["nodes"] = nodes
    save(w, "05_Validation_Fraud_Decision_Agent.json")


# ============================================================================ 03 Visual (teammate)
def build_visual():
    w = json.load(open(SRC / "03_Visual_Inspection_Agent.json", encoding="utf-8"))
    w["id"], w["name"] = "CSVisualAgent03", "03_Visual_Inspection_Agent"
    log = CHANGES.setdefault("03_Visual_Inspection_Agent", [])
    for n in w["nodes"]:
        if n["type"].endswith("executeWorkflowTrigger"):
            n["parameters"] = {"inputSource": "passthrough"}
            n["typeVersion"] = 1.1
            log.append("Sub-workflow trigger set to 'accept all data' (passthrough) so the photos sent by the "
                       "orchestrator arrive as binary files together with claim_id, description and incident_date.")
        if n["type"].endswith("googleGemini"):
            n["credentials"] = GEMINI
            log.append("Gemini credential re-pointed to Fedi's own Gemini key (model and prompt unchanged).")
    w["nodes"].append(sticky("About", "## Visual Inspection Agent\nCalled by the orchestrator with the claim fields and the "
                             "damage photos as binary files (photo_0, photo_1, ...). All photos are analysed in one "
                             "Gemini call. Test alone with the form trigger.", [-420, -260], 380, 200))
    save(w, "03_Visual_Inspection_Agent.json")


# ============================================================================ 04 Invoice (Fedi + Omar)
def build_invoice():
    w = json.load(open(SRC / "03_Invoice_Parser_Agent.json", encoding="utf-8"))
    w["name"] = "04_Invoice_Parser_Agent"
    CHANGES.setdefault("04_Invoice_Parser_Agent (Fedi + Omar)", []).append(
        "Unchanged (same file as the agent folder, renamed 04 because the visual agent is 03).")
    save(w, "04_Invoice_Parser_Agent.json")


# ============================================================================ 01 Ingestion + 02 RAG (Chedi)
def embeddings_node(name, pos):
    return node(name, "@n8n/n8n-nodes-langchain.embeddingsOpenAi", 1.2, pos, {"model": EMBED_MODEL, "options": {}},
                credentials=NVIDIA)


def build_ingestion():
    log = CHANGES.setdefault("01_Policy_Ingestion_Motor (from Chedi's 01_Policy_Ingestion)", [])
    nodes = [
        sticky("About", "## Policy Ingestion (motor)\nRun once (and again after changing the document).\n"
               "Reads the policy wording PDF, splits it clause by clause (structural header injection, as in Chedi's "
               "ingestion), tags each chunk with clause_id / title / product_scope and stores it in the Qdrant "
               f"collection **{COLLECTION}** with NVIDIA embeddings.\n\nBefore a re-run, delete the collection in "
               "Qdrant (http://localhost:6333/dashboard) to avoid duplicates.", [-60, -300], 460, 240),
        node("Run Ingestion", "n8n-nodes-base.manualTrigger", 1, [0, 0]),
        node("Read Policy PDF", "n8n-nodes-base.readWriteFile", 1.1, [220, 0],
             {"fileSelector": f"{DATA}/policy/Motor-Policy-Wording.pdf", "options": {}}),
        node("Extract PDF Text", "n8n-nodes-base.extractFromFile", 1.1, [440, 0], {"operation": "pdf", "options": {}}),
        node("Split Into Clauses", "n8n-nodes-base.code", 2, [660, 0], {"jsCode": js("ingest_split.js")}),
        node("Qdrant Vector Store", "@n8n/n8n-nodes-langchain.vectorStoreQdrant", 1.3, [900, 0], {
            "mode": "insert",
            "qdrantCollection": {"__rl": True, "value": COLLECTION, "mode": "id"},
            "options": {},
        }, credentials=QDRANT),
        embeddings_node("Embeddings NVIDIA", [840, 240]),
        node("Default Data Loader", "@n8n/n8n-nodes-langchain.documentDefaultDataLoader", 1.1, [1020, 240], {
            "jsonMode": "expressionData",
            "jsonData": "={{ $json.pageContent }}",
            "textSplittingMode": "simple",
            "options": {"metadata": {"metadataValues": [
                {"name": "clause_id", "value": "={{ $json.metadata.clause_id }}"},
                {"name": "title", "value": "={{ $json.metadata.title }}"},
                {"name": "part", "value": "={{ $json.metadata.part }}"},
                {"name": "product_scope", "value": "={{ $json.metadata.product_scope }}"},
                {"name": "source", "value": "={{ $json.metadata.source }}"},
            ]}},
        }),
    ]
    conns = {
        "Run Ingestion": link(["Read Policy PDF"]),
        "Read Policy PDF": link(["Extract PDF Text"]),
        "Extract PDF Text": link(["Split Into Clauses"]),
        "Split Into Clauses": link(["Qdrant Vector Store"]),
        **{"Embeddings NVIDIA": ai("ai_embedding", "Qdrant Vector Store")},
        **{"Default Data Loader": ai("ai_document", "Qdrant Vector Store")},
    }
    log += ["Reads the new motor policy wording (data/claimshield/policy/Motor-Policy-Wording.pdf): the original "
            "Policy-Document.pdf is an HDFC *life* group policy, unrelated to car damage claims.",
            "Clause splitter anchored on 'Part X - ' / 'Clause n.m - ' headings (the original regex also split inside "
            "sentences such as '(Part B)'), page footers removed.",
            "Each chunk keeps Chedi's structural header ([Product | Clause]) and gets metadata clause_id, title, part and "
            "product_scope ('all' or 'motor_comprehensive') so retrieval can be filtered by the customer's product.",
            f"New Qdrant collection '{COLLECTION}' (same NVIDIA embedding model {EMBED_MODEL})."]
    save(workflow("CSIngestMotor01", "01_Policy_Ingestion_Motor", nodes, conns), "01_Policy_Ingestion_Motor.json")


def build_rag():
    log = CHANGES.setdefault("02_Policy_RAG_Agent (from Chedi's 02_Policy_RAG_Agent)", [])
    nodes = [
        sticky("About", "## Policy RAG Agent\nCalled by the orchestrator with { claim, policy, visual, invoice }.\n"
               "1. Build a search query from the description and the damaged / invoiced parts.\n"
               f"2. Retrieve the 8 closest clauses from Qdrant ({COLLECTION}), filtered by the customer's product.\n"
               "3. Gemini decides COVERED / EXCLUDED / REQUIRES_REVIEW citing clause IDs.\n"
               "4. Grounding check: only clause IDs that were actually retrieved can be cited.\n\n"
               "Exact amounts (deductible, limits) come from the policy table, never from retrieval.", [-80, -340], 520, 280),
        node("When Executed by Another Workflow", "n8n-nodes-base.executeWorkflowTrigger", 1.1, [0, 0],
             {"inputSource": "passthrough"}),
        node("Test Claim", "n8n-nodes-base.manualTrigger", 1, [0, 200]),
        node("Test Data", "n8n-nodes-base.code", 2, [200, 200], {"jsCode": js("rag_test_data.js")}),
        node("Build Query", "n8n-nodes-base.code", 2, [420, 0], {"jsCode": js("rag_query.js")}),
        node("Retrieve Clauses", "@n8n/n8n-nodes-langchain.vectorStoreQdrant", 1.3, [640, 0], {
            "mode": "load",
            "qdrantCollection": {"__rl": True, "value": COLLECTION, "mode": "id"},
            "prompt": "={{ $json.query }}",
            "topK": 8,
            "includeDocumentMetadata": True,
            "options": {"searchFilterJson": "={{ JSON.stringify({ should: [ { key: 'metadata.product_scope', match: { value: 'all' } }, { key: 'metadata.product_scope', match: { value: $json.product } } ] }) }}"},
        }, credentials=QDRANT, onError="continueErrorOutput", alwaysOutputData=True),
        embeddings_node("Embeddings NVIDIA", [600, 220]),
        node("Build Context", "n8n-nodes-base.code", 2, [880, 0], {"jsCode": js("rag_context.js")}),
        node("Coverage Decision", "@n8n/n8n-nodes-langchain.chainLlm", 1.9, [1100, 0], {
            "promptType": "define", "text": js("rag_prompt.txt"), "batching": {}},
            retryOnFail=True, waitBetweenTries=5000, onError="continueRegularOutput"),
        node("Google Gemini Chat Model", "@n8n/n8n-nodes-langchain.lmChatGoogleGemini", 1.2, [1060, 220],
             {"modelName": GEMINI_MODEL, "options": {"temperature": 0}}, credentials=GEMINI),
        node("Parse Coverage", "n8n-nodes-base.code", 2, [1340, 0], {"jsCode": js("rag_parse.js")}),
        node("Retrieval Error", "n8n-nodes-base.code", 2, [880, 220],
             {"jsCode": "return [{ json: { error: true, reason: 'Policy retrieval failed: ' + String($json.error?.message ?? $json.error ?? 'Qdrant error'), coverage_status: 'REQUIRES_REVIEW', cited_clauses: [], flagged_exclusions: [] } }];"}),
    ]
    conns = {
        "When Executed by Another Workflow": link(["Build Query"]),
        "Test Claim": link(["Test Data"]),
        "Test Data": link(["Build Query"]),
        "Build Query": link(["Retrieve Clauses"]),
        "Retrieve Clauses": link(["Build Context"], ["Retrieval Error"]),
        "Build Context": link(["Coverage Decision"]),
        "Coverage Decision": link(["Parse Coverage"]),
        **{"Embeddings NVIDIA": ai("ai_embedding", "Retrieve Clauses")},
        **{"Google Gemini Chat Model": ai("ai_languageModel", "Coverage Decision")},
    }
    log += ["Callable by the orchestrator (When Executed by Another Workflow) with { claim, policy, visual, invoice }; "
            "manual test data kept.",
            "Retrieve-then-generate instead of an AI Agent with a search tool: the Qdrant node retrieves the 8 closest "
            "clauses, filtered by the customer's product (design §4.4), and one LLM call decides coverage. Fewer calls, "
            "deterministic retrieval, easier to evaluate.",
            "Same output contract as Chedi's agent (coverage_status, cited_clauses, reasoning, flagged_exclusions) + "
            "retrieved_clauses; the JSON text is parsed and checked (only clause IDs that were retrieved can be cited).",
            "Chat model: Gemini (the nemotron-3.5 model timed out on the free NVIDIA tier); embeddings unchanged "
            f"({EMBED_MODEL})."]
    save(workflow("CSPolicyRAG02", "02_Policy_RAG_Agent", nodes, conns), "02_Policy_RAG_Agent.json")


# ============================================================================ 00 Orchestrator
def exec_wf(name, pos, wf_id, wf_name):
    return node(name, "n8n-nodes-base.executeWorkflow", 1.2, pos, {
        "workflowId": {"__rl": True, "value": wf_id, "mode": "list", "cachedResultName": wf_name},
        "options": {"waitForSubWorkflow": True},
    }, onError="continueRegularOutput", alwaysOutputData=True)


def build_orchestrator():
    log = CHANGES.setdefault("00_ClaimShield_Orchestrator (new)", [])
    y0, x = 0, 0
    form_fields = [
        {"fieldLabel": "Policy ID", "placeholder": "POL-1001", "requiredField": True},
        {"fieldLabel": "Incident date", "fieldType": "date", "requiredField": True},
        {"fieldLabel": "Incident location", "placeholder": "Tunis"},
        {"fieldLabel": "Description of the accident", "fieldType": "textarea", "requiredField": True},
        {"fieldLabel": "Claimed amount (TND)", "fieldType": "number", "requiredField": True},
        {"fieldLabel": "Damage photos", "fieldType": "file", "multipleFiles": True, "acceptFileTypes": ".jpg,.jpeg,.png",
         "requiredField": True},
        {"fieldLabel": "Repair invoice", "fieldType": "file", "multipleFiles": False, "acceptFileTypes": ".pdf,.jpg,.jpeg,.png",
         "requiredField": True},
    ]
    nodes = [
        sticky("About", js("orchestrator_about.md"), [-40, -520], 760, 420, 7),
        node("Claim Form", "n8n-nodes-base.formTrigger", 2.6, [0, 0], {
            "formTitle": "ClaimShield AI – submit a motor claim",
            "formDescription": "Internal demo form: the claim is checked by the photo, invoice and policy agents, then scored.",
            "formFields": {"values": form_fields},
            "options": {"appendAttribution": False},
        }, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "cs/form"))),
        node("Claim API", "n8n-nodes-base.webhook", 2.1, [0, 220], {
            "httpMethod": "POST", "path": "claimshield/claims", "authentication": "headerAuth",
            "responseMode": "onReceived", "options": {"responseCode": {"values": {"responseCode": "customCode", "customCode": 202}}},
        }, credentials=WEBHOOK_AUTH, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "cs/api"))),
        node("Prepare Claim", "n8n-nodes-base.code", 2, [240, 100], {"jsCode": js("orc_prepare.js")}),
        node("Photo Checks", "n8n-nodes-base.code", 2, [460, 100], {"jsCode": js("orc_photo_checks.js")}),
        node("Read Photo Register", "n8n-nodes-base.readWriteFile", 1.1, [680, 100],
             {"fileSelector": f"{DATA}/photo_register.json", "options": {}},
             onError="continueRegularOutput", alwaysOutputData=True),
        node("Register Check", "n8n-nodes-base.code", 2, [900, 100], {"jsCode": js("orc_register_check.js")}),
        node("Validation Input", "n8n-nodes-base.code", 2, [1120, 100],
             {"jsCode": "// Stage 1 of the decision agent: required fields, policy, coverage dates (no AI call).\n"
                        "return [{ json: { stage: 'validate', claim: $('Register Check').first().json.claim } }];"}),
        exec_wf("Validate Claim", [1340, 100], "CSDecision05", "05_Validation_Fraud_Decision_Agent"),
        node("Claim Valid?", "n8n-nodes-base.if", 2.2, [1560, 100], {
            "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                           "conditions": [{"id": "valid", "leftValue": "={{ $json.valid }}", "rightValue": True,
                                           "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                           "combinator": "and"}, "looseTypeValidation": True, "options": {}}),
        node("Visual Input", "n8n-nodes-base.code", 2, [1800, 0], {"jsCode": js("orc_visual_input.js")}),
        exec_wf("Visual Inspection", [2020, 0], "CSVisualAgent03", "03_Visual_Inspection_Agent"),
        node("Invoice Input", "n8n-nodes-base.code", 2, [2240, 0], {"jsCode": js("orc_invoice_input.js")}),
        exec_wf("Invoice Parser", [2460, 0], "InvParserAgent03", "04_Invoice_Parser_Agent"),
        node("RAG Input", "n8n-nodes-base.code", 2, [2680, 0], {"jsCode": js("orc_rag_input.js")}),
        exec_wf("Policy RAG", [2900, 0], "CSPolicyRAG02", "02_Policy_RAG_Agent"),
        node("Decision Input", "n8n-nodes-base.code", 2, [3120, 0], {"jsCode": js("orc_decision_input.js")}),
        exec_wf("Fraud Risk & Decision", [3340, 0], "CSDecision05", "05_Validation_Fraud_Decision_Agent"),
        node("Decision Record", "n8n-nodes-base.code", 2, [3560, 0], {"jsCode": js("orc_decision_record.js")}),
        node("Rejected Record", "n8n-nodes-base.code", 2, [1800, 260], {"jsCode": js("orc_rejected_record.js")}),
        # ---- outputs (shared by accepted and rejected claims)
        node("Log Line", "n8n-nodes-base.code", 2, [3800, -260], {"jsCode": js("orc_log_line.js")}),
        node("Append Decision Log", "n8n-nodes-base.readWriteFile", 1.1, [4020, -260], {
            "operation": "write", "fileName": f"{DATA}/decisions_log.jsonl", "dataPropertyName": "log",
            "options": {"append": True}}, onError="continueRegularOutput"),
        node("Updated Photo Register", "n8n-nodes-base.code", 2, [3800, -80], {"jsCode": js("orc_register_update.js")}),
        node("Save Photo Register", "n8n-nodes-base.readWriteFile", 1.1, [4020, -80], {
            "operation": "write", "fileName": f"{DATA}/photo_register.json", "dataPropertyName": "register",
            "options": {}}, onError="continueRegularOutput"),
        node("From Form?", "n8n-nodes-base.if", 2.2, [3800, 100], {
            "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                           "conditions": [{"id": "form", "leftValue": "={{ $json.claim.source }}", "rightValue": "form",
                                           "operator": {"type": "string", "operation": "equals"}}],
                           "combinator": "and"}, "looseTypeValidation": True, "options": {}}),
        node("Show Result", "n8n-nodes-base.form", 2.5, [4020, 100], {
            "operation": "completion", "respondWith": "text",
            "completionTitle": "={{ $json.page.title }}",
            "completionMessage": "={{ $json.page.message }}",
            "options": {}}, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "cs/result"))),
        node("Route", "n8n-nodes-base.switch", 3.2, [3800, 320], {
            "rules": {"values": [
                {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                                "conditions": [{"leftValue": "={{ $json.route }}", "rightValue": r,
                                                "operator": {"type": "string", "operation": "equals"}}],
                                "combinator": "and"}, "renameOutput": True, "outputKey": r}
                for r in ["auto_approve", "human_review", "fraud_investigation"]]},
            "options": {"fallbackOutput": "extra", "renameFallbackOutput": "rejected"}}),
        node("Payment Request (mock)", "n8n-nodes-base.code", 2, [4060, 260], {"jsCode": js("orc_payment.js")}),
        node("Slack On? (review)", "n8n-nodes-base.if", 2.2, [4060, 420], slack_if()),
        node("Ask Adjuster on Slack", "n8n-nodes-base.slack", 2.3, [4280, 420], {
            "operation": "sendAndWait", "select": "channel",
            "channelId": {"__rl": True, "value": "={{ $json.settings.slack_channel }}", "mode": "name"},
            "message": "={{ $json.slack.review_message }}",
            "approvalOptions": {"values": {"approvalType": "double", "approveLabel": "Approve claim",
                                           "disapproveLabel": "Reject claim"}},
            "options": {"limitWaitTime": {"values": {"limitType": "afterTimeInterval", "resumeAmount": 2, "resumeUnit": "days"}}},
        }, credentials=SLACK, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "cs/slack-review")), onError="continueRegularOutput"),
        node("Adjuster Answer", "n8n-nodes-base.code", 2, [4500, 420], {"jsCode": js("orc_adjuster_answer.js")}),
        node("Append Adjuster Log", "n8n-nodes-base.readWriteFile", 1.1, [4720, 420], {
            "operation": "write", "fileName": f"{DATA}/decisions_log.jsonl", "dataPropertyName": "log",
            "options": {"append": True}}, onError="continueRegularOutput"),
        node("Slack On? (fraud)", "n8n-nodes-base.if", 2.2, [4060, 600], slack_if()),
        node("Fraud Alert on Slack", "n8n-nodes-base.slack", 2.3, [4280, 600], {
            "select": "channel",
            "channelId": {"__rl": True, "value": "={{ $json.settings.slack_channel }}", "mode": "name"},
            "text": "={{ $json.slack.fraud_message }}", "otherOptions": {}},
            credentials=SLACK, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "cs/slack-fraud")), onError="continueRegularOutput"),
    ]
    conns = {
        "Claim Form": link(["Prepare Claim"]),
        "Claim API": link(["Prepare Claim"]),
        "Prepare Claim": link(["Photo Checks"]),
        "Photo Checks": link(["Read Photo Register"]),
        "Read Photo Register": link(["Register Check"]),
        "Register Check": link(["Validation Input"]),
        "Validation Input": link(["Validate Claim"]),
        "Validate Claim": link(["Claim Valid?"]),
        "Claim Valid?": link(["Visual Input"], ["Rejected Record"]),
        "Visual Input": link(["Visual Inspection"]),
        "Visual Inspection": link(["Invoice Input"]),
        "Invoice Input": link(["Invoice Parser"]),
        "Invoice Parser": link(["RAG Input"]),
        "RAG Input": link(["Policy RAG"]),
        "Policy RAG": link(["Decision Input"]),
        "Decision Input": link(["Fraud Risk & Decision"]),
        "Fraud Risk & Decision": link(["Decision Record"]),
        "Decision Record": link(["Log Line", "Updated Photo Register", "From Form?", "Route"]),
        "Rejected Record": link(["Log Line", "Updated Photo Register", "From Form?", "Route"]),
        "Log Line": link(["Append Decision Log"]),
        "Updated Photo Register": link(["Save Photo Register"]),
        "From Form?": link(["Show Result"], []),
        "Route": link(["Payment Request (mock)"], ["Slack On? (review)"], ["Slack On? (fraud)"], []),
        "Slack On? (review)": link(["Ask Adjuster on Slack"], []),
        "Ask Adjuster on Slack": link(["Adjuster Answer"]),
        "Adjuster Answer": link(["Append Adjuster Log"]),
        "Slack On? (fraud)": link(["Fraud Alert on Slack"], []),
    }
    log += ["New main workflow (design §4.1/4.3): form or authenticated webhook intake -> photo checks -> validation "
            "-> visual, invoice and policy agents -> decision -> route -> actions and audit log.",
            "Photo checks not done by any agent: EXIF date of each photo (PHOTO_BEFORE_INCIDENT rule) and a file "
            "fingerprint compared with all earlier claims (PHOTO_REUSED rule), register in data/claimshield/photo_register.json.",
            "Every claim (accepted or rejected) is appended to data/claimshield/decisions_log.jsonl (audit trail, design §4.8).",
            "Actions: auto_approve -> mock payment request; human_review -> Slack approve/reject (send and wait); "
            "fraud_investigation -> Slack alert. Slack is off until settings.slack_enabled is true in Prepare Claim.",
            "The result page separates the customer message (never mentions fraud, design §4.8) from the internal summary."]
    save(workflow("CSOrchestrator00", "00_ClaimShield_Orchestrator", nodes, conns), "00_ClaimShield_Orchestrator.json")


def slack_if():
    return {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                           "conditions": [{"id": "slack", "leftValue": "={{ $json.settings.slack_enabled }}", "rightValue": True,
                                           "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                           "combinator": "and"}, "looseTypeValidation": True, "options": {}}


if __name__ == "__main__":
    build_decision(); build_visual(); build_invoice(); build_ingestion(); build_rag(); build_orchestrator()
    md = ["# Integration changes", "", "Teammates' original workflows are unchanged; these are the changes made in the "
          "integration copies (folder `integration/workflows`).", ""]
    for wf, items in CHANGES.items():
        md += [f"## {wf}", *[f"- {i}" for i in items], ""]
    (HERE / "out" / "INTEGRATION_CHANGES.md").write_text("\n".join(md), encoding="utf-8")
    print("credentials:", {"gemini": GEMINI, "qdrant": QDRANT, "slack": SLACK})
