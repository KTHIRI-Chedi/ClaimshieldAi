"""Run 03_Invoice_Parser_Agent on every test invoice and compare with data/invoices/expected.json.

For each file: rebuild the workflow with that file as default input, import it into the
running n8n container, execute it with the n8n CLI and check status / extraction method / total.
Also checks that a missing file raises a clear error. Restores INV-001 as default at the end.

Usage: python scripts/test_invoice_agent.py [file_name ...]
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_invoice_workflow import DEFAULT_FILE, build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTAINER = "claimshield_n8n"
WORKFLOW_ID = "InvParserAgent03"
MISSING = "__missing__.pdf"


def sh(*args, timeout=600):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def deploy(default_file):
    path = build(default_file)
    sh("docker", "cp", str(path), f"{CONTAINER}:/tmp/inv.json")
    r = sh("docker", "exec", CONTAINER, "n8n", "import:workflow", "--input=/tmp/inv.json")
    if "Successfully imported" not in r.stdout + r.stderr:
        raise SystemExit(f"import failed: {r.stdout}{r.stderr}")


def execute():
    # A separate task-broker port avoids clashing with the running n8n server.
    r = sh("docker", "exec", "-e", "N8N_RUNNERS_BROKER_PORT=5690", CONTAINER,
           "n8n", "execute", f"--id={WORKFLOW_ID}", "--rawOutput")
    out = r.stdout
    start = out.find("{")
    if start == -1:
        return None, (out + r.stderr)[-500:]
    data, _ = json.JSONDecoder().raw_decode(out[start:])
    return data, None


def result_of(data):
    run = data["data"]["resultData"]
    err = run.get("error", {}).get("message")
    check = run["runData"].get("Arithmetic Check")
    res = check[0]["data"]["main"][0][0]["json"] if check else None
    return res, err


def main():
    expected = json.loads((ROOT / "data/invoices/expected.json").read_text(encoding="utf-8"))
    expected[MISSING] = {"expected_error": "Invoice file not found"}
    names = sys.argv[1:] or list(expected)
    rows, failures = [], 0
    for name in names:
        exp = expected[name]
        deploy(f"/data/invoices/{name}")
        t0 = time.time()
        data, raw_err = execute()
        secs = time.time() - t0
        res, err = (None, raw_err) if data is None else result_of(data)
        problems = []
        if "expected_error" in exp:
            if not err or exp["expected_error"] not in err:
                problems.append(f"expected error '{exp['expected_error']}', got {err!r}")
        elif res is None:
            problems.append(f"no result: {err}")
        else:
            if res["status"] != exp["expected_status"]:
                problems.append(f"status {res['status']} != {exp['expected_status']}")
            if exp.get("expected_method") and res["extraction_method"] != exp["expected_method"]:
                problems.append(f"method {res['extraction_method']} != {exp['expected_method']}")
            if exp.get("total") is not None and exp.get("tamper") != "total":
                printed = res["invoice"].get("total")
                if printed is None or abs(printed - exp["total"]) > 0.01:
                    problems.append(f"total {printed} != {exp['total']}")
            if exp.get("n_lines") and len(res["invoice"].get("line_items", [])) < exp["n_lines"]:
                problems.append(f"{len(res['invoice'].get('line_items', []))} lines < {exp['n_lines']}")
        failures += bool(problems)
        detail = "; ".join(problems) if problems else (err or "")
        status = res["status"] if res else "error"
        method = res["extraction_method"] if res else "-"
        if res and res.get("extraction"):
            ext = res["extraction"]
            method += f" ({ext['chunks']} part{'s' if ext['chunks'] > 1 else ''}{', fallback' if ext['llm_fallback_used'] else ''})"
        issues = [i["type"] for i in res["arithmetic_check"]["issues"]] + res["review_reasons"] if res else []
        rows.append((name, "PASS" if not problems else "FAIL", status, method, f"{secs:.0f}s", ",".join(issues), detail))
        print(" | ".join(rows[-1]), flush=True)
        if res and problems:
            print(json.dumps(res, indent=1, ensure_ascii=False)[:3000], flush=True)

    deploy(DEFAULT_FILE)
    print(f"\n{len(rows) - failures}/{len(rows)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
