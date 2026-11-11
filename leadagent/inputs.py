"""Read the input CSV, normalise websites and skip duplicate companies."""
import csv
import re
from dataclasses import dataclass
from urllib.parse import urlparse

LEGAL_SUFFIXES = r"\b(pty|ltd|limited|inc|incorporated|plc|co|corp|corporation|group|holdings|the)\b"


@dataclass
class Company:
    name: str
    website: str   # "" if the CSV had none
    domain: str
    row: int       # 1-based CSV data row, for the log


def normalise_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    n = re.sub(LEGAL_SUFFIXES, " ", n)
    return re.sub(r"\s+", " ", n).strip()


def normalise_website(url: str) -> tuple[str, str]:
    url = (url or "").strip()
    if not url:
        return "", ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    return url.rstrip("/"), domain


def _pick(row: dict, *keys: str) -> str:
    lowered = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
    for k in keys:
        if lowered.get(k, "").strip():
            return lowered[k].strip()
    return ""


def load_companies(path: str) -> tuple[list[Company], list[dict]]:
    """Returns (unique companies, skipped rows with a reason)."""
    companies, skipped = [], []
    seen_names, seen_domains = {}, {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            name = _pick(row, "company", "company name", "name")
            website, domain = normalise_website(_pick(row, "website", "url", "site", "domain"))
            if not name:
                skipped.append({"row": i, "company": "", "website": website, "reason": "missing company name"})
                continue
            key = normalise_name(name)
            dup_of = seen_names.get(key) or (seen_domains.get(domain) if domain else None)
            if dup_of:
                skipped.append({"row": i, "company": name, "website": website, "reason": f"duplicate of '{dup_of}'"})
                continue
            seen_names[key] = name
            if domain:
                seen_domains[domain] = name
            companies.append(Company(name=name, website=website, domain=domain, row=i))
    return companies, skipped
