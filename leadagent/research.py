"""Collect public sources for one company: its own site pages, then search results (web + news)."""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from ddgs import DDGS

from . import config
from .fetch import Page, fetch, is_blocked
from .inputs import Company, normalise_name


def _rank_site_links(links: list[dict]) -> list[str]:
    scored = []
    for link in links:
        hay = (link["url"] + " " + link["text"]).lower()
        score = sum(w for kw, w in config.SITE_LINK_KEYWORDS.items() if kw in hay)
        if score:
            scored.append((score, -len(link["url"]), link["url"]))
    scored.sort(reverse=True)
    return [u for _, _, u in scored]


def _mentions_company(company: Company, text: str) -> bool:
    words = [w for w in normalise_name(company.name).split() if len(w) > 2] or normalise_name(company.name).split()
    t = text.lower()
    return all(w in t for w in words[:2])


SEARCH_CACHE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "search")


def _cached_search(kind: str, query: str, use_cache: bool, **kw) -> list[dict]:
    """DuckDuckGo search with a disk cache (reruns are fast and reproducible) and one retry."""
    path = os.path.join(SEARCH_CACHE, hashlib.sha1(f"{kind}|{query}|{kw}".encode()).hexdigest() + ".json")
    if use_cache and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    last = None
    for attempt in range(2):
        try:
            ddgs = DDGS(timeout=10)
            res = ddgs.text(query, **kw) if kind == "text" else ddgs.news(query, **kw)
            os.makedirs(SEARCH_CACHE, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(res, f)
            return res
        except Exception as e:  # rate limits and "no results" both raise
            last = e
            time.sleep(2.5)
    raise last


def short_name(name: str) -> str:
    """'Qube Holdings' -> 'Qube': search engines often do better without legal/group words."""
    keep = [w for w in name.split() if normalise_name(w)]
    return " ".join(keep) or name


def search_sources(company: Company, log: list[dict], use_cache: bool = True) -> list[dict]:
    """Returns candidate {url, title, snippet, kind, date} from web + news search."""
    y = config.TODAY.year
    results, seen = [], set()

    def add(url, title, snippet, kind, date=""):
        if not url or url in seen or is_blocked(url):
            return
        if not _mentions_company(company, f"{title} {snippet} {url}"):
            return
        seen.add(url)
        results.append({"url": url, "title": title, "snippet": snippet, "kind": kind, "date": date})

    names = [company.name] + ([short_name(company.name)] if short_name(company.name) != company.name else [])
    for template in config.SEARCH_QUERIES:
        for name in names:  # fall back to the short name only if the full name finds nothing
            q = template.format(name=name, y=y, y1=y + 1)
            try:
                for r in _cached_search("text", q, use_cache, max_results=6):
                    add(r.get("href"), r.get("title", ""), r.get("body", ""), "search")
                log.append({"step": "search", "query": q, "ok": True})
                break
            except Exception as e:
                log.append({"step": "search", "query": q, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]})
        time.sleep(1.0)
    try:
        for r in _cached_search("news", f"{company.name} Australia", use_cache, max_results=8, timelimit="y"):
            add(r.get("url"), r.get("title", ""), r.get("body", ""), "news", r.get("date", ""))
        log.append({"step": "search", "query": f"news: {company.name} Australia", "ok": True})
    except Exception as e:
        log.append({"step": "search", "query": f"news: {company.name} Australia", "ok": False, "error": f"{type(e).__name__}: {e}"[:200]})

    # Company's own domain first (press releases), then dated news, then the rest.
    def rank(r):
        own = company.domain and urlparse(r["url"]).netloc.lower().removeprefix("www.").endswith(company.domain)
        return (0 if own else 1 if r["kind"] == "news" else 2)
    results.sort(key=rank)
    return results


def gather(company: Company, use_cache: bool = True) -> tuple[list[Page], list[dict]]:
    """Fetch site + search pages. Returns (successfully read pages, log entries)."""
    log: list[dict] = []
    pages: list[Page] = []
    seen_text: set[int] = set()

    def record(p: Page, kind: str):
        if p.ok and hash(p.text) in seen_text:  # same page under another URL (e.g. /en/news vs /news)
            p.ok, p.error = False, "duplicate of a page already read"
        log.append({"step": "fetch", "kind": kind, "url": p.url, "ok": p.ok, "status": p.status,
                    "chars": len(p.text), "cached": p.from_cache, "error": p.error})
        if p.ok:
            seen_text.add(hash(p.text))
            pages.append(p)

    site_urls = []
    if company.website:
        home = fetch(company.website, use_cache=use_cache, want_links=True)
        record(home, "site:home")
        site_urls = _rank_site_links(home.links)[: config.MAX_SITE_PAGES - 1]
    else:
        log.append({"step": "input", "ok": False, "error": "no website in CSV; using search results only"})

    hits = search_sources(company, log, use_cache=use_cache)
    search_urls = [h["url"] for h in hits if h["url"] not in site_urls][: config.MAX_SEARCH_PAGES]
    news_dates = {h["url"]: h["date"] for h in hits if h["date"]}

    jobs = [(u, "site") for u in site_urls] + [(u, "search") for u in search_urls]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for (url, kind), p in zip(jobs, pool.map(lambda j: fetch(j[0], use_cache=use_cache), jobs)):
            if not p.published and url in news_dates:
                p.published = news_dates[url][:10]
            record(p, kind)
    return pages, log
