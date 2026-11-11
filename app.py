"""Wilmarcs Lead Desk: a web app for the whole assignment flow.

  1. Upload the Task 2 company CSV
  2. Task 1 runs (research, score, draft) with live progress, and results show with sources and log
  3. Task 3: edit the best drafts (before/after + why), approve/reject
  4. Pilot plan: funnel targets, Monday metrics, risks (downloadable)
  5. Hand-off: Instantly CSV or push into a PAUSED campaign. Nothing is ever sent from here.

Run:  python app.py   then open http://localhost:5000
"""
import csv
import io
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from leadagent import config, funnel, instantly
from leadagent.draft import MAX_WORDS, _word_count
from leadagent.inputs import load_companies
from leadagent.pipeline import run_batch
from leadagent.report import write_outputs

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(ROOT, "runs")
SAMPLE_CSV = os.path.join(ROOT, "input", "companies.csv")
os.makedirs(RUNS, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
_lock = threading.Lock()


# ---------- storage (one folder per run, plain JSON files) ----------

def run_dir(run_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9-]{6,40}", run_id or ""):
        abort(404)
    d = os.path.join(RUNS, run_id)
    if not os.path.isdir(d):
        abort(404)
    return d


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


def meta(run_id):
    return read_json(os.path.join(run_dir(run_id), "meta.json"), {})


def all_runs():
    out = []
    for rid in sorted(os.listdir(RUNS), reverse=True):
        m = read_json(os.path.join(RUNS, rid, "meta.json"), None)
        if m:
            out.append(m)
    return out


def results(run_id):
    return read_json(os.path.join(run_dir(run_id), "results.json"), {"rows": [], "log": [], "skipped": []})


def edits(run_id):
    return read_json(os.path.join(run_dir(run_id), "edits.json"), {})


# ---------- background research job ----------

def _job(run_id, csv_path, limit, use_cache):
    d = os.path.join(RUNS, run_id)
    m = read_json(os.path.join(d, "meta.json"), {})
    try:
        companies, skipped = load_companies(csv_path)
        if limit:
            companies = companies[:limit]
        m.update(status="running", total=len(companies), done=0, skipped=len(skipped), current=[c.name for c in companies[:3]])
        write_json(os.path.join(d, "meta.json"), m)
        finished = []

        def on_done(c, row, log):
            with _lock:
                finished.append({"company": c.name, "score": row.get("Fit score", 0),
                                 "draft": bool(row.get("Email subject")), "flags": row.get("Flags", "")[:120]})
                m.update(done=len(finished), finished=finished)
                pending = [x.name for x in companies if x.name not in {f["company"] for f in finished}]
                m["current"] = pending[:3]
                write_json(os.path.join(d, "meta.json"), m)

        rows, log = run_batch(companies, skipped, use_cache=use_cache, workers=3, on_done=on_done)
        write_json(os.path.join(d, "results.json"), {"rows": rows, "log": log, "skipped": skipped})
        write_outputs(rows, log, skipped, d)
        m.update(status="done", finished_at=datetime.now().isoformat(timespec="seconds"),
                 drafts=sum(1 for r in rows if r.get("Email subject")))
    except Exception as e:
        m.update(status="error", error=f"{type(e).__name__}: {e}")
    write_json(os.path.join(d, "meta.json"), m)


# ---------- helpers for Task 3 ----------

def drafted_rows(run_id):
    return [r for r in results(run_id)["rows"] if r.get("Email subject")]


def final_drafts(run_id, only_approved=True):
    """Merge each tool draft with the human's edits. 'after' = edited text, or the original if untouched."""
    e = edits(run_id)
    out = []
    for r in drafted_rows(run_id):
        ed = e.get(r["Company"], {})
        status = ed.get("status", "Pending")
        if only_approved and status != "Approve":
            continue
        out.append({
            "company": r["Company"], "website": r.get("Website", ""), "rank": r.get("Rank"),
            "fit_score": r.get("Fit score"), "signal": r.get("Timing signal", ""), "signal_date": r.get("Signal date", ""),
            "signal_source": r.get("Signal source", ""), "film": r.get("Suggested film", ""),
            "original_subject": r.get("Email subject", ""), "original_body": r.get("Email draft", ""),
            "subject": ed.get("subject") or r.get("Email subject", ""),
            "body": ed.get("body") or r.get("Email draft", ""),
            "sources": r.get("Email sources", ""), "note": ed.get("note", ""), "status": status,
            "email": ed.get("email", ""), "first_name": ed.get("first_name", ""),
            "top5": bool(ed.get("top5")), "showcase": bool(ed.get("showcase")),
            "edited": bool(ed.get("body") and ed.get("body") != r.get("Email draft")),
        })
    return out


# ---------- pages ----------

@app.route("/")
def index():
    sample = []
    if os.path.exists(SAMPLE_CSV):
        with open(SAMPLE_CSV, encoding="utf-8-sig") as f:
            sample = list(csv.DictReader(f))
    return render_template("index.html", runs=all_runs(), sample=sample, key_ok=bool(config.GEMINI_API_KEY))


@app.post("/runs")
def create_run():
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    d = os.path.join(RUNS, run_id)
    os.makedirs(d)
    csv_path = os.path.join(d, "input.csv")
    f = request.files.get("csv")
    if f and f.filename:
        f.save(csv_path)
        source = f.filename
    else:
        with open(SAMPLE_CSV, "rb") as src, open(csv_path, "wb") as dst:
            dst.write(src.read())
        source = "Task 2 list (input/companies.csv)"
    limit = int(request.form.get("limit") or 0)
    use_cache = request.form.get("fresh") != "on"
    write_json(os.path.join(d, "meta.json"), {
        "id": run_id, "source": source, "created": datetime.now().isoformat(timespec="seconds"),
        "status": "queued", "total": 0, "done": 0, "limit": limit, "cache": use_cache})
    threading.Thread(target=_job, args=(run_id, csv_path, limit, use_cache), daemon=True).start()
    return redirect(url_for("run_page", run_id=run_id))


@app.get("/api/runs/<run_id>/status")
def run_status(run_id):
    return jsonify(meta(run_id))


@app.get("/runs/<run_id>")
def run_page(run_id):
    m = meta(run_id)
    if m.get("status") != "done":
        return render_template("progress.html", m=m)
    res = results(run_id)
    fetches = [e for e in res["log"] if e.get("step") == "fetch"]
    stats = {
        "companies": len(res["rows"]), "skipped": len(res["skipped"]),
        "drafts": sum(1 for r in res["rows"] if r.get("Email subject")),
        "sources_read": sum(1 for e in fetches if e.get("ok")), "pages_failed": sum(1 for e in fetches if not e.get("ok")),
        "red_flags": sum(1 for r in res["rows"] if r.get("_detail", {}).get("red_flags")),
    }
    log_by_company = {}
    for e in res["log"]:
        log_by_company.setdefault(e.get("company", ""), []).append(e)
    return render_template("results.html", m=m, rows=res["rows"], skipped=res["skipped"], stats=stats,
                           log_by_company=log_by_company, edits=edits(run_id))


@app.get("/runs/<run_id>/review")
def review_page(run_id):
    m = meta(run_id)
    if m.get("status") != "done":
        return redirect(url_for("run_page", run_id=run_id))
    return render_template("review.html", m=m, drafts=final_drafts(run_id, only_approved=False), max_words=MAX_WORDS)


@app.post("/api/runs/<run_id>/edits")
def save_edit(run_id):
    data = request.get_json(force=True)
    company = data.get("company", "")
    if company not in {r["Company"] for r in drafted_rows(run_id)}:
        abort(400)
    path = os.path.join(run_dir(run_id), "edits.json")
    with _lock:
        e = read_json(path, {})
        keep = {k: data.get(k) for k in ("subject", "body", "note", "status", "email", "first_name", "top5", "showcase")}
        keep["saved_at"] = datetime.now().isoformat(timespec="seconds")
        e[company] = keep
        write_json(path, e)
    return jsonify({"ok": True, "words": _word_count(data.get("body", ""))})


@app.get("/runs/<run_id>/plan")
def plan_page(run_id):
    a = funnel.from_form(request.args)
    f = funnel.compute(a)
    drafts = final_drafts(run_id, only_approved=False)
    top5 = [d for d in drafts if d["top5"]][:5]
    showcase = [d for d in drafts if d["showcase"]][:2]
    return render_template("plan.html", m=meta(run_id), f=f, a=a, top5=top5, showcase=showcase)


@app.get("/runs/<run_id>/handoff")
def handoff_page(run_id):
    key, campaign = instantly.configured()
    return render_template("handoff.html", m=meta(run_id), approved=final_drafts(run_id),
                           key_ok=bool(key), campaign=campaign)


@app.post("/api/runs/<run_id>/instantly/push")
def instantly_push(run_id):
    key, campaign = instantly.configured()
    campaign = (request.get_json(silent=True) or {}).get("campaign_id") or campaign
    if not key or not campaign:
        return jsonify({"ok": False, "error": "Set INSTANTLY_API_KEY (and a campaign id) in .env first."}), 400
    res = instantly.push_leads(final_drafts(run_id), key, campaign)
    write_json(os.path.join(run_dir(run_id), "instantly_push.json"), {"at": time.time(), "results": res})
    return jsonify({"ok": True, "results": res})


@app.get("/api/runs/<run_id>/instantly/analytics")
def instantly_analytics(run_id):
    key, campaign = instantly.configured()
    campaign = request.args.get("campaign_id") or campaign
    if not key or not campaign:
        return jsonify({"ok": False, "error": "Set INSTANTLY_API_KEY and a campaign id first."}), 400
    return jsonify(instantly.campaign_analytics(key, campaign))


# ---------- downloads ----------

def _edited_workbook(drafts) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Edited drafts"
    cols = [("Rank", 6), ("Company", 24), ("Status", 10), ("Timing signal", 36), ("Signal date", 11),
            ("Signal source", 36), ("Suggested film", 28), ("Tool subject (before)", 28), ("Tool draft (before)", 60),
            ("Edited subject (after)", 28), ("Edited draft (after)", 60), ("Words (after)", 8),
            ("What I changed and why", 50), ("Email sources", 40)]
    ws.append([c for c, _ in cols])
    for i, (_, w) in enumerate(cols, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        ws.cell(1, i).font = Font(bold=True, color="FFFFFF")
        ws.cell(1, i).fill = PatternFill("solid", fgColor="1F2937")
    for d in drafts:
        ws.append([d["rank"], d["company"], d["status"], d["signal"], d["signal_date"], d["signal_source"], d["film"],
                   d["original_subject"], d["original_body"], d["subject"], d["body"], _word_count(d["body"]),
                   d["note"], d["sources"]])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@app.get("/runs/<run_id>/download/<kind>")
def download(run_id, kind):
    d = run_dir(run_id)
    files = {"review.xlsx": "review.xlsx", "review.csv": "review.csv", "run_log.jsonl": "run_log.jsonl",
             "input.csv": "input.csv"}
    if kind in files:
        return send_file(os.path.join(d, files[kind]), as_attachment=True, download_name=f"{run_id}-{kind}")
    if kind == "edited_drafts.xlsx":
        drafts = [x for x in final_drafts(run_id, only_approved=False) if x["top5"]] or \
                 [x for x in final_drafts(run_id, only_approved=False) if x["edited"]]
        return Response(_edited_workbook(drafts), headers={"Content-Disposition": f"attachment; filename={kind}"},
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if kind == "instantly.csv":
        return Response(instantly.to_csv(final_drafts(run_id)), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=instantly_leads.csv"})
    if kind == "pilot_plan.md":
        a = funnel.from_form(request.args)
        drafts = final_drafts(run_id, only_approved=False)
        md = render_template("pilot_plan.md", f=funnel.compute(a), a=a,
                             top5=[x for x in drafts if x["top5"]][:5], showcase=[x for x in drafts if x["showcase"]][:2])
        return Response(md, mimetype="text/markdown", headers={"Content-Disposition": "attachment; filename=pilot_plan.md"})
    abort(404)


@app.template_filter("pct")
def pct(v):
    return f"{v * 100:.0f}%"


@app.template_filter("n1")
def n1(v):
    return f"{v:,.1f}" if v < 100 else f"{v:,.0f}"


@app.template_filter("domain")
def domain(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else url


@app.template_filter("linkify")
def linkify(text):
    from markupsafe import Markup, escape
    t = str(escape(text or ""))
    t = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)
    return Markup(t.replace("\n", "<br>"))


if __name__ == "__main__":
    app.run(debug=False, port=int(os.getenv("PORT", "5000")), threaded=True)
