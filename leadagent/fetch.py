"""Fetch public pages (HTML or PDF) without ever raising: failures come back as Page(ok=False)."""
import hashlib
import io
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader

from . import config

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings are noise for text extraction

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "pages")
MAX_PDF_BYTES = 15_000_000
MAX_PDF_PAGES = 20

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "en-AU,en;q=0.9"})


@dataclass
class Page:
    url: str
    ok: bool
    status: int | None = None
    title: str = ""
    published: str = ""   # page date from metadata, if any
    text: str = ""
    error: str = ""
    links: list[dict] = field(default_factory=list)  # internal links (homepage only)
    elapsed_s: float = 0.0
    excerpt: str = ""     # the part of `text` the LLM is shown (and that quotes are verified against)
    from_cache: bool = False


def is_blocked(url: str) -> bool:
    u = url.lower()
    return any(b in u for b in config.BLOCKED_DOMAINS)


def _cache_path(url: str) -> str:
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for p in reader.pages[:MAX_PDF_PAGES]:
        parts.append(p.extract_text() or "")
    return "\n".join(parts)


DATE_META = ("article:published_time", "og:published_time", "datePublished", "date", "pubdate",
             "publish-date", "dc.date", "article:modified_time")


def _title_and_date(soup: BeautifulSoup) -> tuple[str, str]:
    """Title + publish date from meta tags / JSON-LD / <time>. (Avoids htmldate, whose
    compiled `regex` dependency is blocked by Windows Smart App Control on some machines.)"""
    title = soup.title.get_text(strip=True) if soup.title else ""
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or m.get("itemprop") or "").strip()
        if key in DATE_META and m.get("content"):
            if d := re.search(r"\d{4}-\d{2}-\d{2}", m["content"]):
                return title, d.group(0)
    for script in soup.find_all("script", type="application/ld+json"):
        if d := re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', script.string or ""):
            return title, d.group(1)
    t = soup.find("time", datetime=True)
    if t and (d := re.search(r"\d{4}-\d{2}-\d{2}", t["datetime"])):
        return title, d.group(0)
    return title, ""


def _internal_links(html: str, base_url: str) -> list[dict]:
    base_domain = urlparse(base_url).netloc.lower().removeprefix("www.")
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0].rstrip("/")
        dom = urlparse(href).netloc.lower().removeprefix("www.")
        if not href.startswith("http") or not (dom == base_domain or dom.endswith("." + base_domain)):
            continue
        if href in seen or href == base_url.rstrip("/"):
            continue
        seen.add(href)
        links.append({"url": href, "text": a.get_text(" ", strip=True)[:80]})
    return links


def fetch(url: str, use_cache: bool = True, want_links: bool = False) -> Page:
    if is_blocked(url):
        return Page(url=url, ok=False, error="blocked source (not a permitted public page)")
    cp = _cache_path(url)
    if use_cache and os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            return Page(**{**json.load(f), "from_cache": True})

    start = time.time()
    page = Page(url=url, ok=False)
    for attempt in range(2):
        try:
            r = _session.get(url, timeout=config.HTTP_TIMEOUT, allow_redirects=True, stream=True)
            page.status = r.status_code
            if r.status_code >= 400:
                page.error = f"HTTP {r.status_code}"
                if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(2)
                    continue
                break
            ctype = r.headers.get("Content-Type", "").lower()
            if "pdf" in ctype or url.lower().endswith(".pdf"):
                data = r.raw.read(MAX_PDF_BYTES + 1, decode_content=True)
                if len(data) > MAX_PDF_BYTES:
                    page.error = "PDF too large, skipped"
                    break
                page.text = _pdf_text(data)
                page.title = os.path.basename(urlparse(url).path)
            else:
                if "charset" not in ctype:  # requests falls back to ISO-8859-1, which garbles UTF-8 pages
                    r.encoding = "utf-8"
                html = r.text
                soup = BeautifulSoup(html, "html.parser")
                page.title, page.published = _title_and_date(soup)
                page.text = trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True) or ""
                if len(page.text) < 300:  # JS-heavy or link-heavy page: fall back to all visible text
                    page.text = soup.get_text(" ", strip=True)
                if want_links:
                    page.links = _internal_links(html, r.url)
            page.text = " ".join(page.text.split())[:60_000]
            page.ok = bool(page.text.strip())
            page.error = "" if page.ok else "no readable text on page"
            break
        except requests.RequestException as e:
            page.error = f"{type(e).__name__}: {str(e)[:150]}"
            if attempt == 0:
                time.sleep(1.5)
        except Exception as e:  # malformed PDF/HTML must never stop the run
            page.error = f"parse error {type(e).__name__}: {str(e)[:150]}"
            break
    page.elapsed_s = round(time.time() - start, 2)

    if page.ok:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cp, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in asdict(page).items() if k not in ("from_cache", "excerpt")}, f)
    return page
