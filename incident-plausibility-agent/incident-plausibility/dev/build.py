"""Builds the importable n8n workflow JSON from the Code-node sources in ./src.

Prompts live in ./prompts as versioned files. ACTIVE picks which version goes into the
workflow; dev/eval/run_eval.js compares versions on the labeled test claims.
"""
import json
import sys
import uuid
from pathlib import Path

SRC = Path(__file__).parent / "src"
PROMPTS = Path(__file__).parent / "prompts"
OUT = Path(sys.argv[1])

ACTIVE = {
    "extraction": "extraction.v3.js",
    # Both reconstruction prompts are inlined; the LLM settings node picks one at run time.
    "reconstruction": ["reconstruction.v2.js", "reconstruction.ft1.js"],
}

# Placeholder comment in a Code node -> file inlined in its place.
INLINE = {
    "// __VOCAB__": PROMPTS / "vocabulary.js",
    "// __GROUNDING__": PROMPTS / "grounding.js",
    "// __LLM__": PROMPTS / "llm.js",
    "// __PROMPT_EXTRACTION__": PROMPTS / ACTIVE["extraction"],
}


def prompts_block(files):
    # Each prompt file defines `const PROMPT`; a block scope per file lets several coexist.
    parts = ["const PROMPTS = {};"]
    for f in files:
        parts.append("{\n" + (PROMPTS / f).read_text(encoding="utf-8").rstrip() + "\nPROMPTS[PROMPT.version] = PROMPT;\n}")
    return "\n".join(parts) + "\n"


def code(name):
    js = (SRC / name).read_text(encoding="utf-8")
    for marker, path in INLINE.items():
        if marker in js:
            js = js.replace(marker, path.read_text(encoding="utf-8").rstrip() + "\n")
    if "// __PROMPTS_RECONSTRUCTION__" in js:
        js = js.replace("// __PROMPTS_RECONSTRUCTION__", prompts_block(ACTIVE["reconstruction"]))
    assert "__PROMPT" not in js and "__VOCAB__" not in js and "__GROUNDING__" not in js, name
    return js


def nid():
    return str(uuid.uuid4())


nodes = []


def add(name, type_, version, pos, params, **extra):
    nodes.append({"parameters": params, "id": nid(), "name": name, "type": type_,
                  "typeVersion": version, "position": pos, **extra})


def code_node(name, file, pos):
    add(name, "n8n-nodes-base.code", 2, pos, {"jsCode": code(file)})


def params(pairs):
    return {"parameters": [{"name": k, "value": v} for k, v in pairs]}


NOMINATIM_HEADERS = params([
    ("User-Agent", "ClaimShieldAI-student-project/0.1 (replace with your team contact)"),
    ("Accept-Language", "en"),
])
# Map/weather calls must not stop the claim: on failure the agent reports status "partial".
SOFT_FAIL = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000,
             "alwaysOutputData": True, "onError": "continueRegularOutput"}
# Free tiers rate-limit: retry on errors (incl. 429) and send one call at a time.
LLM_RETRY = {"retryOnFail": True, "maxTries": 5, "waitBetweenTries": 5000}


def geocode(name, url_expr, pos):
    # The full URL comes from Normalize input: /search for an address, /reverse for a map pin.
    add(name, "n8n-nodes-base.httpRequest", 4.2, pos, {
        "url": url_expr,
        "sendHeaders": True,
        "headerParameters": NOMINATIM_HEADERS,
        "options": {"timeout": 15000},
    }, **SOFT_FAIL)


def llm_call(name, role, pos):
    # Any OpenAI-compatible provider: URL and body come from the request builder (see
    # "LLM settings"); the key is a Header Auth credential "Authorization: Bearer <key>".
    add(name, "n8n-nodes-base.httpRequest", 4.2, pos, {
        "method": "POST",
        "url": "={{ $json.url }}",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($json.body) }}",
        "options": {
            "timeout": 120000,
            # Pause between the calls of one node (the 3 reconstruction calls), from LLM settings.
            "batching": {"batch": {"batchSize": 1,
                                   "batchInterval": "={{ $('LLM settings').first().json.providers." + role + ".callIntervalMs }}"}},
        },
    }, **LLM_RETRY)


Y = 300
add("When called by orchestrator", "n8n-nodes-base.executeWorkflowTrigger", 1, [0, Y - 100], {})
add("Manual test", "n8n-nodes-base.manualTrigger", 1, [0, Y + 100], {})
code_node("Sample claim", "sample_claim.js", [220, Y + 100])
code_node("Normalize input", "normalize_input.js", [440, Y])
code_node("LLM settings", "llm_settings.js", [440, Y + 220])
geocode("Geocode incident", "={{ $('Normalize input').first().json.incident_geocode_url }}", [660, Y])
code_node("Build queries", "build_queries.js", [1100, Y])
def if_true(name, expr, pos):
    add(name, "n8n-nodes-base.if", 2, pos, {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
            "conditions": [{
                "id": nid(),
                "leftValue": expr,
                "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "options": {},
    })


if_true("Location found?", "={{ $json.has_location }}", [1320, Y])
def overpass(name, index, timeout_ms, pos):
    # One try per server with a short timeout; on failure the next node tries a mirror.
    add(name, "n8n-nodes-base.httpRequest", 4.2, pos, {
        "method": "POST",
        "url": f"={{{{ $('Build queries').first().json.overpass_urls[{index}] }}}}",
        "sendHeaders": True,
        "headerParameters": params([("User-Agent", "ClaimShieldAI-student-project/0.1")]),
        "sendBody": True,
        "contentType": "form-urlencoded",
        "bodyParameters": params([("data", "={{ $('Build queries').first().json.overpass_query }}")]),
        "options": {"timeout": timeout_ms},
    }, alwaysOutputData=True, onError="continueRegularOutput")


MAP_OK = "={{ Array.isArray($json.elements) }}"
overpass("Road context (Overpass)", 0, 15000, [1540, Y - 200])
if_true("Map data OK?", MAP_OK, [1760, Y - 200])
overpass("Road context (mirror 1)", 1, 15000, [1980, Y - 120])
if_true("Mirror 1 OK?", MAP_OK, [2200, Y - 120])
overpass("Road context (mirror 2)", 2, 30000, [2420, Y - 60])
add("Weather (Open-Meteo)", "n8n-nodes-base.httpRequest", 4.2, [2640, Y - 200], {
    "url": "={{ $('Build queries').first().json.weather_url }}",
    "options": {"timeout": 15000},
}, **SOFT_FAIL)
code_node("Build context", "build_context.js", [1980, Y])
code_node("Build extraction request", "build_extraction_request.js", [2640, Y])
llm_call("Extract facts (LLM)", "extraction", [2860, Y])
code_node("Verify extracted facts", "verify_facts.js", [3080, Y])
# Free tiers count tokens per minute: wait after the extraction call before the next calls.
add("Pause (free-tier limit)", "n8n-nodes-base.wait", 1.1, [3190, Y + 160], {
    "resume": "timeInterval",
    "amount": "={{ $('LLM settings').first().json.pause_seconds }}",
    "unit": "seconds",
}, webhookId=nid())
code_node("Build reconstruction request", "build_reconstruction_request.js", [3300, Y])
llm_call("Reconstruct incident x3 (LLM)", "reconstruction", [3520, Y])
code_node("Score and assemble", "score_and_assemble.js", [3740, Y])
# Last node = what the orchestrator's Execute Workflow node receives (shared agent result format).
code_node("Plausibility score (output)", "output_contract.js", [3960, Y])
add("Note", "n8n-nodes-base.stickyNote", 1, [0, -260], {
    "content": (
        "## Incident Plausibility Agent\n"
        "Checks the claimant's story against the real world (OpenStreetMap, Open-Meteo) and the repair invoice "
        "against an LLM reconstruction of the incident. It never sees the photos: the Visual Inspection agent "
        "covers those.\n\n"
        "**Setup:** pick the AI provider in **LLM settings** (default: Groq, free). On both LLM nodes, select a "
        "Header Auth credential with Name `Authorization` and Value `Bearer <your key>`. Put your team contact "
        "in the Nominatim User-Agent. Run **Manual test** to try the sample claim.\n\n"
        "**Output (last node):** the shared ClaimShield agent result: score, score_max, weighted_score, "
        "warning_signs[] with points, confidence and evidence, summary, details. "
        "See contracts/agent_result.schema.json."
    ),
    "height": 300, "width": 620,
})


def link(a, b, out=0):
    conns.setdefault(a, {"main": []})
    main = conns[a]["main"]
    while len(main) <= out:
        main.append([])
    main[out].append({"node": b, "type": "main", "index": 0})


conns = {}
link("When called by orchestrator", "Normalize input")
link("Manual test", "Sample claim")
link("Sample claim", "Normalize input")
link("Normalize input", "LLM settings")
link("LLM settings", "Geocode incident")
link("Geocode incident", "Build queries")
link("Build queries", "Location found?")
link("Location found?", "Road context (Overpass)", 0)
link("Location found?", "Build context", 1)
link("Road context (Overpass)", "Map data OK?")
link("Map data OK?", "Weather (Open-Meteo)", 0)
link("Map data OK?", "Road context (mirror 1)", 1)
link("Road context (mirror 1)", "Mirror 1 OK?")
link("Mirror 1 OK?", "Weather (Open-Meteo)", 0)
link("Mirror 1 OK?", "Road context (mirror 2)", 1)
link("Road context (mirror 2)", "Weather (Open-Meteo)")
link("Weather (Open-Meteo)", "Build context")
link("Build context", "Build extraction request")
link("Build extraction request", "Extract facts (LLM)")
link("Extract facts (LLM)", "Verify extracted facts")
link("Verify extracted facts", "Pause (free-tier limit)")
link("Pause (free-tier limit)", "Build reconstruction request")
link("Build reconstruction request", "Reconstruct incident x3 (LLM)")
link("Reconstruct incident x3 (LLM)", "Score and assemble")
link("Score and assemble", "Plausibility score (output)")

workflow = {
    "name": "ClaimShield - Incident Plausibility Agent",
    "nodes": nodes,
    "connections": conns,
    "settings": {"executionOrder": "v1"},
    "pinData": {},
    "active": False,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {OUT} ({len(nodes)} nodes)")
