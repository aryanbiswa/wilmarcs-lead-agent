"""Ask the LLM for facts + verbatim evidence, then verify every quote against the cited page.

A fact survives only if its quote is actually found in the text of the page it cites.
Anything else becomes NOT_FOUND, so later steps cannot use it.
"""
import re
from datetime import date, datetime

from rapidfuzz import fuzz

from . import config
from .fetch import Page
from .llm import LLMError, generate_json

NOT_FOUND = "Not found (no source)"
QUOTE_MATCH_THRESHOLD = 90  # rapidfuzz partial_ratio on normalised text

SYSTEM = (
    "You are a careful B2B research assistant. You only report facts that are explicitly stated "
    "in the numbered SOURCES you are given. For every fact you give the source id and a short quote "
    "copied word-for-word from that source. If a fact is not stated, return null. Never guess."
)

PROMPT = """Company: {name}
Website: {website}
Today's date: {today}

From the SOURCES below, extract the following as JSON. Each fact object has
"value", "source" (e.g. "S3") and "quote" (8-30 words copied EXACTLY from that source). Use null for the whole object if not stated.

{{
  "industry":   {{"value": "short industry label", "source": "...", "quote": "..."}},
  "size_band":  {{"value": "employee or revenue range, e.g. '1,000-5,000 employees' or 'AUD 100m-500m revenue'", "employees_estimate": integer or null, "source": "...", "quote": "..."}},
  "city":       {{"value": "Australian city of HQ or main office", "source": "...", "quote": "..."}},
  "asx_listed": {{"value": true, "source": "...", "quote": "..."}},
  "runs_events": {{"value": true, "source": "...", "quote": "..."}},
  "signals": [
    {{"type": one of {signal_types},
      "summary": "one line: what is happening",
      "date": "YYYY-MM-DD or YYYY-MM (when the event happens / the report or announcement was released)",
      "source": "...", "quote": "..."}}
  ],
  "red_flags": [
    {{"summary": "takeover / acquisition / delisting / administration / major restructure affecting THIS company",
      "date": "YYYY-MM-DD or YYYY-MM", "source": "...", "quote": "..."}}
  ]
}}

Rules:
- "asx_listed" only if a source says the company is listed on the ASX (or shows an ASX ticker). "runs_events" only if the company itself organises conferences, summits, expos or festivals.
- signals: up to 4, only for THIS company (not a competitor or a sponsor), only if dated, and only if recent (released within the last 12 months) or upcoming. Prefer the quote that contains the date.
- Events: return the NEXT UPCOMING edition (dated after today) of each conference, expo, awards night or festival the
  company runs, even if a past edition is also mentioned. Never return an event that has already happened.
- A signal must genuinely be one of the listed types. A facility opening, results announcement, share-price move or
  contract win is NOT a signal. An "anniversary" means the company itself marks N years. If nothing fits, return [].
- red_flags: [] if none. Only events that could freeze marketing spend.
- Copy quotes exactly, including numbers. Do not paraphrase inside "quote".

SOURCES:
{sources}
"""


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^a-z0-9$%&' -]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote: str, page_text: str) -> bool:
    q, t = _norm(quote or ""), _norm(page_text)
    if len(q) < 12:
        return False
    return q in t or fuzz.partial_ratio(q, t) >= QUOTE_MATCH_THRESHOLD


SIGNAL_WORDS = re.compile(
    r"summit|conference|expo|festival|forum|congress|sustainab|impact report|esg report|annual report|"
    r"launch|rebrand|new brand|new name|anniversary|celebrat|\d+ years|years of|funding|raised|series [a-d]|"
    r"takeover|acquisition|acquire|delist|administration|\b202[5-9]\b", re.I)
DATE_LIKE = re.compile(
    r"\b\d{1,2}(?:\s*[-–]\s*\d{1,2})?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+20\d\d\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d\d\b|\b20\d\d-\d\d-\d\d\b", re.I)


def make_excerpt(text: str, limit: int = config.MAX_CHARS_PER_PAGE, window: int = 350) -> str:
    """Page opening + windows around dates and signal words, so a date on page 40 of a report
    isn't lost to truncation. Windows are cut from the real text, so quotes stay verifiable."""
    if len(text) <= limit:
        return text
    # Score each window: a signal word next to a full date beats either one alone.
    windows = []
    for m in SIGNAL_WORDS.finditer(text, 1200):
        a, b = max(0, m.start() - window), min(len(text), m.end() + window)
        chunk = text[a:b]
        score = 2 * len(DATE_LIKE.findall(chunk)) + len(SIGNAL_WORDS.findall(chunk))
        windows.append((score, a, b))
    chosen, used = [(0, 1200)], 1200
    for _, a, b in sorted(windows, reverse=True):
        if any(a < y and b > x for x, y in chosen):  # overlaps something already taken
            continue
        chosen.append((a, b))
        used += b - a
        if used >= limit:
            break
    return " … ".join(text[a:b] for a, b in sorted(chosen))[:limit]


def format_sources(pages: list[Page]) -> tuple[str, dict[str, Page]]:
    by_id, blocks = {}, []
    for i, p in enumerate(pages, start=1):
        sid = f"S{i}"
        p.excerpt = make_excerpt(p.text)
        by_id[sid] = p
        blocks.append(f"[{sid}] URL: {p.url}\nTitle: {p.title}\nPage date: {p.published or 'unknown'}\n"
                      f"Text: {p.excerpt}")
    return "\n\n".join(blocks), by_id


def _verify(fact, by_id: dict[str, Page], issues: list[str], label: str):
    """Return the fact with its source URL attached, or None if it can't be backed by its page."""
    if not isinstance(fact, dict) or fact.get("value") in (None, "", False):
        return None
    page = by_id.get(str(fact.get("source", "")).strip())
    if not page:
        issues.append(f"{label}: cited unknown source {fact.get('source')!r}; dropped")
        return None
    # Only check against the text the model actually saw.
    if quote_found(fact.get("quote", ""), page.excerpt):
        return {**fact, "url": page.url}
    snapped = snap_to_source(fact.get("quote", ""), page.excerpt, must_contain=str(fact.get("date", ""))[:4])
    if snapped:
        issues.append(f"{label}: quote was inexact; replaced with the matching text from {page.url}")
        return {**fact, "quote": snapped, "url": page.url}
    issues.append(f"{label}: quote not found on {page.url}; dropped")
    return None


def snap_to_source(quote: str, text: str, must_contain: str = "", min_overlap: float = 0.8) -> str | None:
    """If the model's quote is a near-miss (dropped words or symbols), return the real page text
    it best matches, so the evidence shown is always the page's own words.
    Slides a window ~1.6x the quote's length over the page and keeps the one holding most quote words."""
    q_words = _norm(quote or "").split()
    if len(q_words) < 5:
        return None
    words = text.split()
    size, best, best_span = int(len(q_words) * 1.6) + 2, 0.0, None
    q_set = set(q_words)
    for i in range(0, max(1, len(words) - size + 1)):
        window = words[i:i + size]
        overlap = len(q_set & set(_norm(" ".join(window)).split())) / len(q_set)
        if overlap > best:
            best, best_span = overlap, " ".join(window)
    if best < min_overlap or not best_span or (must_contain and must_contain not in best_span):
        return None
    return best_span


RED_FLAG_WORDS = re.compile(r"scheme implementation|takeover|delist|voluntary administration|receivership|"
                            r"agreed to be acquired|to be acquired by", re.I)


def keyword_red_flags(name: str, pages: list[Page]) -> list[dict]:
    """Deterministic backstop for the LLM: a red-flag phrase within 200 chars of the company's name."""
    first = name.split()[0].lower()
    for p in pages:
        for m in RED_FLAG_WORDS.finditer(p.excerpt):
            span = p.excerpt[max(0, m.start() - 200): m.end() + 200]
            if first in span.lower():
                return [{"value": f"possible {m.group(0).lower()} (keyword match, check)", "url": p.url,
                         "quote": span.strip()}]
    return []


def date_supported(signal: dict, by_id: dict[str, Page]) -> bool:
    """The signal's year (or FYyy) must appear in the quote, within ~400 chars of it, or as the page date."""
    year = signal["parsed_date"].year
    marks = (str(year), f"fy{str(year)[2:]}", f"fy{str(year + 1)[2:]}")
    page = next((p for p in by_id.values() if p.url == signal["url"]), None)
    if any(m in signal["quote"].lower() for m in marks):
        return True
    if page is None:
        return False
    if page.published.startswith(str(year)):
        return True
    loc = fuzz.partial_ratio_alignment(signal["quote"].lower(), page.excerpt.lower())
    around = page.excerpt[max(0, loc.dest_start - 400): loc.dest_end + 400].lower() if loc else ""
    return any(m in around for m in marks)


def parse_date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    return None


SIGNAL_PROMPT = """Company: {name}
Today's date: {today}

Go through EVERY source below and list every dated timing signal for THIS company:
- conference_or_summit: the next upcoming edition (after today) of any conference, expo, awards or festival it runs
- sustainability_report: a sustainability / impact / ESG / annual report released in the last 12 months
- rebrand, funding_round, anniversary (the company itself marks N years), product_launch
Also list red flags: a takeover, acquisition of THIS company, delisting or administration.

Return JSON: {{"signals": [{{"type": one of {signal_types}, "summary": "...", "date": "YYYY-MM-DD or YYYY-MM",
"source": "S3", "quote": "8-30 words copied EXACTLY from that source, ideally containing the date"}}],
"red_flags": [{{"summary": "...", "date": "...", "source": "...", "quote": "..."}}]}}
Use [] when there are none. Never guess.

SOURCES:
{sources}
"""


def extract_facts(name: str, website: str, pages: list[Page], use_cache: bool = True) -> dict:
    sources, by_id = format_sources(pages)
    fmt = dict(name=name, website=website or "unknown", today=config.TODAY.isoformat(),
               signal_types=config.SIGNAL_TYPES, sources=sources)
    raw = generate_json(PROMPT.format(**fmt), system=SYSTEM, use_cache=use_cache, temperature=0.0)
    # Second, signals-only pass: a small model misses signals in long inputs, so ask again with one job.
    # Both passes go through the same verification, so this raises recall without letting guesses in.
    try:
        extra = generate_json(SIGNAL_PROMPT.format(**fmt), system=SYSTEM, use_cache=use_cache, temperature=0.0)
        seen = {(x.get("type"), x.get("date")) for x in raw.get("signals") or []}
        raw["signals"] = (raw.get("signals") or []) + [x for x in extra.get("signals") or []
                                                         if (x.get("type"), x.get("date")) not in seen]
        raw["red_flags"] = (raw.get("red_flags") or []) + (extra.get("red_flags") or [])
    except LLMError:
        pass  # first pass alone is still a valid result
    issues: list[str] = []
    facts = {k: _verify(raw.get(k), by_id, issues, k)
             for k in ("industry", "size_band", "city", "asx_listed", "runs_events")}

    signals = []
    for s in raw.get("signals") or []:
        if s.get("type") not in config.SIGNAL_TYPES:
            issues.append(f"signal: unknown type {s.get('type')!r}; dropped")
            continue
        v = _verify({**s, "value": s.get("summary")}, by_id, issues, f"signal ({s.get('type')})")
        if v:
            v["parsed_date"] = parse_date(v.get("date", ""))
            if v["parsed_date"] and not date_supported(v, by_id):
                issues.append(f"signal ({v['type']}): date {v.get('date')} not stated near the quote; treated as undated")
                v["parsed_date"] = None
            signals.append(v)
    facts["signals"] = signals
    facts["red_flags"] = [v for f in raw.get("red_flags") or []
                          if (v := _verify({**f, "value": f.get("summary")}, by_id, issues, "red flag"))]
    if not facts["red_flags"]:
        facts["red_flags"] = keyword_red_flags(name, pages)
    facts["issues"] = issues
    return facts


def timeliness(d: date | None, signal_type: str) -> tuple[int, str]:
    """0-35 points: how good a reason to reach out *now* this dated signal is."""
    if d is None:
        return 10, "undated"
    days = (d - config.TODAY).days
    if signal_type == "conference_or_summit":
        if 14 <= days <= 180:
            return 35, f"in {days} days"
        if 180 < days <= 365:
            return 25, f"in {days // 30} months"
        if 0 <= days < 14:
            return 18, "too close to plan coverage"
        if days < 0:  # the brief asks for *upcoming* events; a past one is not a reason to write now
            return 5, "already happened"
        return 5, "stale"
    # Released things: the fresher the better; a future date means an announced upcoming launch.
    if days > 0:
        return 30 if days <= 180 else 20, "upcoming"
    age = -days
    if age <= 90:
        return 35, f"{age} days ago"
    if age <= 180:
        return 28, f"{age // 30} months ago"
    if age <= 365:
        return 15, f"{age // 30} months ago"
    return 3, "over a year old"


MIN_SIGNAL_POINTS = 15  # below this (stale, undated) a signal is not a reason to write today


def best_signal(signals: list[dict], issues: list[str] | None = None) -> dict | None:
    for s in signals:
        s["timeliness_pts"], s["timeliness_note"] = timeliness(s.get("parsed_date"), s["type"])
    usable = [s for s in signals if s["timeliness_pts"] >= MIN_SIGNAL_POINTS]
    if issues is not None:
        issues += [f"signal ({s['type']}, {s.get('date')}): {s['timeliness_note']}; not used"
                   for s in signals if s not in usable]
    return max(usable, key=lambda s: s["timeliness_pts"]) if usable else None
