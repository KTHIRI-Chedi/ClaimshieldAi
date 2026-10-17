"""Run 03_Invoice_Parser_Agent on any invoice file (e.g. real garage invoices) and print what the
Fraud Risk & Decision agent will receive. No expected result: read the output and check it by hand.

Put real invoices in data/invoices/real/ (git-ignored: customer data must never be committed).

Usage: python scripts/run_invoice_agent.py data/invoices/real/facture1.pdf [more files ...]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_invoice_workflow import DEFAULT_FILE  # noqa: E402
from test_invoice_agent import ROOT, deploy, execute, result_of  # noqa: E402


def container_path(arg):
    path = Path(arg).resolve()
    data = (ROOT / "data").resolve()
    if not path.is_relative_to(data):
        raise SystemExit(f"{arg}: the file must be under {data} (mounted as /data in n8n)")
    return "/data/" + path.relative_to(data).as_posix()


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    try:
        for arg in sys.argv[1:]:
            deploy(container_path(arg))
            t0 = time.time()
            data, raw_err = execute()
            res, err = (None, raw_err) if data is None else result_of(data)
            print(f"\n=== {arg} ({time.time() - t0:.0f}s)")
            if res is None:
                print("ERROR:", err)
                continue
            inv = res["invoice"]
            print(f"status={res['status']}  totals_match={res['totals_match']}  method={res['extraction_method']}"
                  f"  parts={res['extraction']['chunks']}  fallback={res['extraction']['llm_fallback_used']}")
            print(f"invoice {inv.get('invoice_number')} | {inv.get('garage_name')} | {inv.get('invoice_date')}"
                  f" | total {inv.get('total')} {inv.get('currency') or ''}")
            for li in res["line_items"]:
                print(f"  [{li['type']:5}] {li['part']}: {li['quantity']} x {li['unit_price']} = {li['line_total']}")
            if res["arithmetic_issue"]:
                print("arithmetic_issue:", res["arithmetic_issue"])
            if res["review_reasons"]:
                print("review_reasons:", ", ".join(res["review_reasons"]))
            if res["ungrounded_amounts"]:
                print("ungrounded_amounts:", json.dumps(res["ungrounded_amounts"], ensure_ascii=False))
    finally:
        deploy(DEFAULT_FILE)


if __name__ == "__main__":
    main()
