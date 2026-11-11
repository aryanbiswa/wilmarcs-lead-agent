"""Instantly hand-off. Leads go into a campaign the user created and that stays PAUSED.

This module never starts a campaign or sends an email (the brief forbids sending real emails).
A human reviews the campaign in Instantly and launches it themselves.
"""
import csv
import io
import os

import requests

API = "https://api.instantly.ai/api/v2"
CSV_COLUMNS = ["email", "first_name", "last_name", "company_name", "website", "subject", "body",
               "signal", "signal_source", "fit_score"]


def instantly_rows(final_drafts: list[dict]) -> list[dict]:
    return [{
        "email": d.get("email", ""),
        "first_name": d.get("first_name", ""),
        "last_name": "",
        "company_name": d["company"],
        "website": d.get("website", ""),
        "subject": d["subject"],
        "body": d["body"],
        "signal": d.get("signal", ""),
        "signal_source": d.get("signal_source", ""),
        "fit_score": d.get("fit_score", ""),
    } for d in final_drafts]


def to_csv(final_drafts: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    w.writerows(instantly_rows(final_drafts))
    return buf.getvalue()


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def push_leads(final_drafts: list[dict], api_key: str, campaign_id: str) -> list[dict]:
    """Add each approved lead (with a published business email) to the paused campaign.
    The campaign's sequence should use {{subject}} and {{body}} custom variables."""
    results = []
    for row in instantly_rows(final_drafts):
        if not row["email"]:
            results.append({"company": row["company_name"], "ok": False, "error": "no email entered; skipped"})
            continue
        payload = {
            "campaign": campaign_id, "email": row["email"], "first_name": row["first_name"],
            "company_name": row["company_name"], "website": row["website"],
            "custom_variables": {"subject": row["subject"], "body": row["body"],
                                 "signal_source": row["signal_source"]},
        }
        try:
            r = requests.post(f"{API}/leads", headers=_headers(api_key), json=payload, timeout=20)
            ok = r.status_code in (200, 201)
            results.append({"company": row["company_name"], "ok": ok,
                            "error": "" if ok else f"HTTP {r.status_code}: {r.text[:200]}"})
        except requests.RequestException as e:
            results.append({"company": row["company_name"], "ok": False, "error": str(e)[:200]})
    return results


def campaign_analytics(api_key: str, campaign_id: str) -> dict:
    """Read-only tracking: sent, opens, replies, bounces for the campaign."""
    try:
        r = requests.get(f"{API}/campaigns/analytics", headers=_headers(api_key),
                         params={"id": campaign_id}, timeout=20)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return {"ok": True, "data": r.json()}
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)[:200]}


def configured() -> tuple[str, str]:
    return os.getenv("INSTANTLY_API_KEY", ""), os.getenv("INSTANTLY_CAMPAIGN_ID", "")
