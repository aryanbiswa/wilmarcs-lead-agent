"""The research pipeline shared by the CLI (run.py) and the web app (app.py)."""
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .draft import draft_email
from .extract import NOT_FOUND, best_signal, extract_facts
from .inputs import Company
from .llm import LLMError
from .research import gather
from .score import buyer_role, score, segment_of


def _val(fact) -> str:
    return fact["value"] if fact else NOT_FOUND


def _src(fact) -> str:
    return fact["url"] if fact else NOT_FOUND


def process(company: Company, use_cache: bool) -> tuple[dict, list[dict]]:
    t0 = time.time()
    row = {"Company": company.name, "Website": company.website or NOT_FOUND, "Status": "Pending"}
    flags: list[str] = []
    pages, log = gather(company, use_cache=use_cache)
    failed = sum(1 for e in log if e["step"] == "fetch" and not e["ok"])
    if failed:
        flags.append(f"{failed} page(s) failed to load (see Log)")

    if not pages:
        flags.append("no readable public pages; nothing researched")
        row.update({"Fit score": 0, "Fit reason": "no sources could be read", "Flags": "; ".join(flags),
                    "Email draft": "NO DRAFT: no sources could be read."})
        return row, log

    try:
        t_llm = time.time()
        facts = extract_facts(company.name, company.website, pages, use_cache=use_cache)
        log.append({"step": "llm", "ok": True, "query": f"extraction {time.time() - t_llm:.1f}s"})
    except LLMError as e:
        log.append({"step": "llm", "ok": False, "error": f"extraction failed: {e}"})
        row.update({"Fit score": 0, "Fit reason": "LLM extraction failed", "Flags": f"LLM error: {e}",
                    "Email draft": "NO DRAFT: research step failed."})
        return row, log
    signal = best_signal(facts["signals"], facts["issues"])
    for issue in facts["issues"]:
        log.append({"step": "verify", "ok": False, "error": issue})
    for rf in facts["red_flags"]:
        flags.append(f"RED FLAG: {rf['value']} ({rf['url']})")
    segment = segment_of(facts, signal)
    buyer = buyer_role(segment, signal)
    fit, reason, parts = score(facts, signal, segment)
    log.append({"step": "score", "ok": True, "error": "", "query": str(parts)})

    row.update({
        "Fit score": fit, "Fit reason": reason, "Segment": segment,
        "Industry": _val(facts["industry"]), "Industry source": _src(facts["industry"]),
        "City": _val(facts["city"]), "City source": _src(facts["city"]),
        "Size band": _val(facts["size_band"]), "Size source": _src(facts["size_band"]),
        "Buyer role": buyer,
    })

    if not signal:
        flags.append("no verified, dated timing signal: needs human research")
        row.update({"Timing signal": NOT_FOUND, "Signal date": "", "Signal source": NOT_FOUND,
                    "Email draft": "NO DRAFT: no verified timing signal, so the tool will not guess one."})
    else:
        row.update({"Timing signal": f"[{signal['type'].replace('_', ' ')}] {signal['summary']}",
                    "Signal date": signal.get("date", ""), "Signal source": signal["url"],
                    "Signal evidence (quote)": f"\"{signal['quote']}\""})
        try:
            d = draft_email(company.name, facts, signal, buyer, use_cache=use_cache)
            row.update({"Suggested film": d["film_type"], "Email subject": d["subject"], "Email draft": d["body"],
                        "Email sources": d["sources"], "Word count": d["word_count"]})
            if d["problems"]:
                flags.append("draft failed checks: " + "; ".join(d["problems"]))
            log.append({"step": "draft", "ok": not d["problems"], "query": f"attempts={d['attempts']}",
                        "error": "; ".join(d["problems"])})
        except LLMError as e:
            flags.append(f"draft failed: {e}")
            log.append({"step": "draft", "ok": False, "error": str(e)})

    row["_detail"] = {"score_parts": parts, "issues": facts["issues"],
                      "red_flags": [{"text": r["value"], "url": r["url"], "quote": r["quote"]} for r in facts["red_flags"]],
                      "sources_read": [{"url": p.url, "title": p.title} for p in pages]}
    row["Flags"] = "; ".join(flags)
    log.append({"step": "done", "ok": True, "query": f"{time.time() - t0:.1f}s, {len(pages)} sources read"})
    return row, log


def run_batch(companies: list[Company], skipped: list[dict], use_cache: bool = True, workers: int = 3,
              on_done: Callable[[Company, dict, list[dict]], None] | None = None) -> tuple[list[dict], list[dict]]:
    """Research every company (in parallel), rank by fit. Returns (rows, log_rows)."""
    rows, log_rows = [], []

    def run_one(c: Company):
        try:
            return process(c, use_cache=use_cache)
        except Exception as e:  # last-resort guard: one bad company never stops the batch
            return ({"Company": c.name, "Website": c.website, "Status": "Pending", "Fit score": 0,
                     "Fit reason": "tool error", "Flags": f"unexpected error: {type(e).__name__}: {e}",
                     "Email draft": "NO DRAFT: tool error."},
                    [{"step": "crash-guard", "ok": False, "error": f"{type(e).__name__}: {e}"}])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for c, (row, log) in zip(companies, pool.map(run_one, companies)):
            rows.append(row)
            log_rows += [{"company": c.name, **e} for e in log]
            if on_done:
                on_done(c, row, log)

    rows.sort(key=lambda r: r.get("Fit score", 0), reverse=True)
    for i, r in enumerate(rows, start=1):
        r["Rank"] = i
    log_rows += [{"company": s["company"], "step": "skip", "ok": False, "error": s["reason"]} for s in skipped]
    return rows, log_rows
