"""Wilmarcs lead research agent (command line). The web app is app.py.

    python run.py input/companies.csv              # research, score, draft -> output/review.xlsx
    python run.py input/companies.csv --limit 3    # quick test on the first 3 companies
    python run.py --approved output/review.xlsx    # list rows a human marked Approve (still sends nothing)
"""
import argparse
import sys

from leadagent import config
from leadagent.inputs import load_companies
from leadagent.pipeline import run_batch
from leadagent.report import write_outputs


def show_approved(xlsx_path: str):
    from openpyxl import load_workbook
    ws = load_workbook(xlsx_path)["Review"]
    headers = [c.value for c in ws[1]]
    rows = [dict(zip(headers, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    approved = [r for r in rows if (r.get("Status") or "").lower() == "approve"]
    print(f"{len(approved)} approved of {len(rows)}. This tool never sends email; copy these into your sender.\n")
    for r in approved:
        print(f"--- {r['Company']} | {r['Email subject']}\n{r['Email draft']}\n{r['Email sources']}\n")


def main():
    ap = argparse.ArgumentParser(description="Research, score and draft outreach for Australian companies.")
    ap.add_argument("csv", nargs="?", help="input CSV with company,website columns")
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    ap.add_argument("--limit", type=int, default=0, help="only process the first N unique companies")
    ap.add_argument("--workers", type=int, default=3, help="companies researched in parallel")
    ap.add_argument("--no-cache", action="store_true", help="re-fetch pages and re-ask the LLM")
    ap.add_argument("--approved", metavar="XLSX", help="print rows marked Approve in a reviewed workbook")
    args = ap.parse_args()

    if args.approved:
        return show_approved(args.approved)
    if not args.csv:
        ap.error("give an input CSV")
    if not config.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is not set. Put it in a .env file (see .env.example).")

    companies, skipped = load_companies(args.csv)
    if args.limit:
        companies = companies[: args.limit]
    print(f"{len(companies)} unique companies, {len(skipped)} skipped "
          f"({', '.join(s['company'] + ': ' + s['reason'] for s in skipped) or 'none'})")

    def progress(c, row, log):
        ok = sum(1 for e in log if e.get("step") == "fetch" and e["ok"])
        print(f"  {row.get('Fit score', 0):>3}  {c.name:<35} {ok} sources  {row.get('Flags', '')[:70]}")

    rows, log_rows = run_batch(companies, skipped, use_cache=not args.no_cache, workers=args.workers, on_done=progress)
    paths = write_outputs(rows, log_rows, skipped, args.out)
    print(f"\nReview list: {paths['xlsx']}\nCSV copy:    {paths['csv']}\nRun log:     {paths['log']}")
    print("Nothing was sent. Open the Review sheet and set each Status to Approve, Edit or Reject.")


if __name__ == "__main__":
    main()
