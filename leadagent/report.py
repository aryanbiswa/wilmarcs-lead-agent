"""Write the human review workbook (Review / Log / Skipped / Scoring) plus CSV and JSONL copies."""
import csv
import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .score import __doc__ as SCORING_DOC

REVIEW_COLUMNS = [
    ("Rank", 6), ("Status", 11), ("Reviewer notes", 24), ("Company", 22), ("Website", 26),
    ("Fit score", 8), ("Fit reason", 44), ("Segment", 22),
    ("Industry", 20), ("Industry source", 26), ("City", 12), ("City source", 26),
    ("Size band", 18), ("Size source", 26), ("Buyer role", 30),
    ("Timing signal", 40), ("Signal date", 12), ("Signal source", 30), ("Signal evidence (quote)", 40),
    ("Suggested film", 30), ("Email subject", 26), ("Email draft", 70), ("Email sources", 40),
    ("Word count", 7), ("Flags", 40),
]
HEADER_FILL = PatternFill("solid", fgColor="1F2937")
LINK_COLUMNS = {"Website", "Industry source", "City source", "Size source", "Signal source"}


def write_outputs(rows: list[dict], log_rows: list[dict], skipped: list[dict], out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    paths = {k: os.path.join(out_dir, f) for k, f in
             (("xlsx", "review.xlsx"), ("csv", "review.csv"), ("log", "run_log.jsonl"))}

    wb = Workbook()
    ws = wb.active
    ws.title = "Review"
    headers = [c for c, _ in REVIEW_COLUMNS]
    ws.append(headers)
    for i, (_, w) in enumerate(REVIEW_COLUMNS, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")

    for r in rows:
        ws.append([r.get(h, "") for h in headers])
        for col, h in enumerate(headers, start=1):
            cell = ws.cell(ws.max_row, col)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if h in LINK_COLUMNS and str(cell.value).startswith("http"):
                cell.hyperlink, cell.style = cell.value, "Hyperlink"
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    dv = DataValidation(type="list", formula1='"Pending,Approve,Edit,Reject"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"B2:B{max(ws.max_row, 2)}")
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = ws.dimensions

    log_ws = wb.create_sheet("Log")
    log_headers = ["company", "step", "kind", "query", "url", "ok", "status", "chars", "cached", "error"]
    log_ws.append(log_headers)
    for c in log_ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
    for e in log_rows:
        log_ws.append([str(e.get(h, "")) for h in log_headers])
    for col, w in zip("ABCDEFGHIJ", (22, 9, 12, 40, 60, 6, 7, 7, 7, 50)):
        log_ws.column_dimensions[col].width = w

    sk = wb.create_sheet("Skipped")
    sk.append(["row", "company", "website", "reason"])
    for s in skipped:
        sk.append([s["row"], s["company"], s["website"], s["reason"]])

    sc = wb.create_sheet("How scoring works")
    for line in SCORING_DOC.strip().splitlines():
        sc.append([line])
    sc.append([])
    sc.append(["Status: set each row to Approve, Edit or Reject. Nothing is sent by this tool."])
    sc.column_dimensions["A"].width = 90
    wb.save(paths["xlsx"])

    with open(paths["csv"], "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(paths["log"], "w", encoding="utf-8") as f:
        for e in log_rows:
            f.write(json.dumps(e, default=str) + "\n")
    return paths
