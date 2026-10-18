"""Builds the importable n8n workflow from dev/form.html and the Code-node sources in dev/src.

Usage: python dev/build.py claim_form_workflow.json
"""
import json
import sys
import uuid
from pathlib import Path

DEV = Path(__file__).parent
OUT = Path(sys.argv[1])


def code(name):
    js = (DEV / "src" / name).read_text(encoding="utf-8")
    if "__TEMPLATE__" in js:
        html = (DEV / "form.html").read_text(encoding="utf-8")
        assert html.count("__CONFIG__") == 1, "form.html must contain __CONFIG__ exactly once"
        js = js.replace("__TEMPLATE__", json.dumps(html, ensure_ascii=False))
    return js


def nid():
    return str(uuid.uuid4())


nodes = []
conns = {}


def add(name, type_, version, pos, params, **extra):
    nodes.append({"parameters": params, "id": nid(), "name": name, "type": type_,
                  "typeVersion": version, "position": pos, **extra})


def link(a, b, out=0):
    main = conns.setdefault(a, {"main": []})["main"]
    while len(main) <= out:
        main.append([])
    main[out].append({"node": b, "type": "main", "index": 0})


def webhook(name, method, path, pos):
    # allowedOrigins "*": the page may run in n8n's sandboxed iframe, whose origin is "null".
    add(name, "n8n-nodes-base.webhook", 2, pos, {
        "httpMethod": method,
        "path": path,
        "responseMode": "responseNode",
        "options": {"allowedOrigins": "*"},
    }, webhookId=nid())


def code_node(name, file, pos):
    add(name, "n8n-nodes-base.code", 2, pos, {"jsCode": code(file)})


def respond_json(name, body_expr, pos, status=200):
    opts = {} if status == 200 else {"responseCode": status}
    add(name, "n8n-nodes-base.respondToWebhook", 1.1, pos, {
        "respondWith": "json", "responseBody": body_expr, "options": opts})


def if_true(name, expr, pos):
    add(name, "n8n-nodes-base.if", 2, pos, {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
            "conditions": [{
                "id": nid(), "leftValue": expr, "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "options": {},
    })


# ---- 1. GET /claim-form: the claim page ----
Y1 = 0
webhook("Claim page (GET /claim-form)", "GET", "claim-form", [0, Y1])
code_node("Render form page", "render_form.js", [240, Y1])
add("Send page", "n8n-nodes-base.respondToWebhook", 1.1, [480, Y1], {
    "respondWith": "text",
    "responseBody": "={{ $json.html }}",
    "options": {"responseHeaders": {"entries": [
        {"name": "Content-Type", "value": "text/html; charset=utf-8"}]}},
})
link("Claim page (GET /claim-form)", "Render form page")
link("Render form page", "Send page")

# ---- 2. GET /claim-geocode: address search and pin-to-address for the page ----
Y2 = 260
webhook("Address lookup (GET /claim-geocode)", "GET", "claim-geocode", [0, Y2])
code_node("Build geocode request", "build_geocode_request.js", [240, Y2])
if_true("Lookup valid?", "={{ !!$json.url }}", [480, Y2])
add("Nominatim", "n8n-nodes-base.httpRequest", 4.2, [720, Y2 - 80], {
    "url": "={{ $json.url }}",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "User-Agent", "value": "ClaimShieldAI-student-project/0.1 (replace with your team contact)"},
        {"name": "Accept-Language", "value": "en"},
    ]},
    "options": {"timeout": 10000},
}, retryOnFail=True, maxTries=2, waitBetweenTries=1500,
    alwaysOutputData=True, onError="continueRegularOutput")
code_node("Shape geocode response", "shape_geocode_response.js", [960, Y2 - 80])
respond_json("Send address", "={{ JSON.stringify($json) }}", [1200, Y2 - 80])
respond_json("Send lookup error",
             '={{ JSON.stringify({ error: "Send lat and lon, or q with at least 3 characters." }) }}',
             [720, Y2 + 100], status=400)
link("Address lookup (GET /claim-geocode)", "Build geocode request")
link("Build geocode request", "Lookup valid?")
link("Lookup valid?", "Nominatim", 0)
link("Lookup valid?", "Send lookup error", 1)
link("Nominatim", "Shape geocode response")
link("Shape geocode response", "Send address")

# ---- 3. POST /claim-submit: receive, validate, answer 202, hand over ----
Y3 = 560
webhook("Claim submission (POST /claim-submit)", "POST", "claim-submit", [0, Y3])
code_node("Validate submission", "validate_submission.js", [240, Y3])
if_true("Valid?", "={{ $json.valid }}", [480, Y3])
code_node("Create claim", "create_claim.js", [720, Y3 - 80])
respond_json(
    "Send claim ID (202)",
    "={{ JSON.stringify({ claim_id: $json.claim.claim_id, status: 'received', "
    "message: 'We have received your claim. You will get the decision by email.' }) }}",
    [960, Y3 - 80], status=202)
add("Run orchestrator", "n8n-nodes-base.executeWorkflow", 1, [1200, Y3 - 80], {
    "source": "database", "workflowId": "", "options": {},
}, disabled=True,
    notes="Enable and pick the main ClaimShield workflow. It receives $json.claim plus the files "
          "photo_1..photo_n and invoice as binary data.")
respond_json("Send errors (400)", "={{ JSON.stringify({ errors: $json.errors }) }}",
             [720, Y3 + 100], status=400)
link("Claim submission (POST /claim-submit)", "Validate submission")
link("Validate submission", "Valid?")
link("Valid?", "Create claim", 0)
link("Valid?", "Send errors (400)", 1)
link("Create claim", "Send claim ID (202)")
link("Send claim ID (202)", "Run orchestrator")

add("Note", "n8n-nodes-base.stickyNote", 1, [0, -360], {
    "content": (
        "## ClaimShield AI: claim intake\n"
        "Three webhooks in one workflow. **Activate the workflow** and open "
        "`<your n8n URL>/webhook/claim-form` in a browser.\n\n"
        "1. **GET /claim-form** serves the claim page (map pin, GPS button, photo and PDF upload).\n"
        "2. **GET /claim-geocode** is the page's address search, through Nominatim.\n"
        "3. **POST /claim-submit** validates the claim, answers 202 with the claim ID, then hands "
        "it to the orchestrator.\n\n"
        "**Setup:** put a team contact in the Nominatim User-Agent, then enable **Run orchestrator** "
        "and pick the main workflow."
    ),
    "height": 320, "width": 640,
})

workflow = {
    "name": "ClaimShield - Claim Intake Form",
    "nodes": nodes,
    "connections": conns,
    "settings": {"executionOrder": "v1"},
    "pinData": {},
    "active": False,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {OUT} ({len(nodes)} nodes)")
