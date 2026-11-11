"""Deterministic 0-100 fit score, so every point can be explained.

  Timing signal  35  how timely the best verified, dated signal is
  Segment fit    25  verified ASX listing or verified event organiser
  Size band      20  mid-size companies buy AUD 8-40k films without agency rosters
  Location       10  Sydney team first, Melbourne close second
  Buyer clarity  10  a signal tells us which function owns the budget
  Red flags     -20  a sourced takeover / delisting / administration (spend likely frozen)
"""
from . import config
from .extract import NOT_FOUND


def segment_of(facts: dict, signal: dict | None) -> str:
    asx, events = bool(facts.get("asx_listed")), bool(facts.get("runs_events"))
    if asx and events:
        return config.SEGMENTS[1] if signal and signal["type"] == "conference_or_summit" else config.SEGMENTS[0]
    if asx:
        return config.SEGMENTS[0]
    if events:
        return config.SEGMENTS[1]
    return "Unverified segment"


def buyer_role(segment: str, signal: dict | None) -> str:
    if signal:
        return config.SIGNAL_PLAYBOOK[signal["type"]][1] + " (inferred from signal type)"
    if segment == config.SEGMENTS[0]:
        return "Head of Sustainability / Corporate Affairs (inferred from segment)"
    if segment == config.SEGMENTS[1]:
        return "Events / Marketing Director (inferred from segment)"
    return NOT_FOUND


def _size_points(size: dict | None) -> tuple[int, str]:
    if not size:
        return 5, "size unknown"
    n = size.get("employees_estimate")
    if not isinstance(n, int):
        return 10, size["value"]
    if 200 <= n <= 5000:
        return 20, f"~{n:,} staff"
    if 5000 < n <= 20000:
        return 15, f"~{n:,} staff"
    if n > 20000:
        return 10, f"~{n:,} staff (likely agency roster)"
    if 50 <= n < 200:
        return 12, f"~{n:,} staff"
    return 5, f"~{n:,} staff (small budget)"


def _location_points(city: dict | None) -> tuple[int, str]:
    if not city:
        return 2, "city unknown"
    c = city["value"].lower()
    if "sydney" in c or "nsw" in c:
        return 10, "Sydney"
    if "melbourne" in c or "vic" in c:
        return 9, "Melbourne"
    return 5, city["value"]


def score(facts: dict, signal: dict | None, segment: str) -> tuple[int, str, dict]:
    t_pts = signal["timeliness_pts"] if signal else 0
    seg_pts = 25 if segment in config.SEGMENTS else 8
    size_pts, size_note = _size_points(facts.get("size_band"))
    loc_pts, loc_note = _location_points(facts.get("city"))
    buyer_pts = 10 if signal else (5 if segment in config.SEGMENTS else 0)
    penalty = -20 if facts.get("red_flags") else 0
    total = max(0, t_pts + seg_pts + size_pts + loc_pts + buyer_pts + penalty)

    if signal:
        lead = f"{signal['type'].replace('_', ' ')} {signal.get('date', '')} ({signal['timeliness_note']})"
    else:
        lead = "no verified timing signal"
    reason = f"{lead}; {segment}; {size_note}; {loc_note}."
    if penalty:
        reason += f" RED FLAG: {facts['red_flags'][0]['value']}."
    parts = {"timing": t_pts, "segment": seg_pts, "size": size_pts, "location": loc_pts, "buyer": buyer_pts,
             "red_flag": penalty}
    return total, reason, parts
