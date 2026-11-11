"""Task 3 targets: work backwards from projects per quarter to weekly emails, replies and calls."""
import math
from dataclasses import asdict, dataclass

WEEKS_PER_QUARTER = 13


@dataclass
class Assumptions:
    projects_per_quarter: int = 6       # Sydney team capacity (brief)
    call_to_project: float = 0.25       # discovery call -> signed project (timed, qualified leads)
    positive_reply_to_call: float = 0.5  # interested reply -> call booked
    reply_rate: float = 0.08            # any reply per prospect over the whole sequence
    positive_share: float = 0.5         # share of replies that are interested
    sequence_steps: int = 3             # first email + 2 follow-ups
    per_inbox_daily_cap: int = 30       # safe sends per warmed inbox per day


def compute(a: Assumptions) -> dict:
    calls_q = a.projects_per_quarter / a.call_to_project
    positive_q = calls_q / a.positive_reply_to_call
    prospects_q = positive_q / (a.reply_rate * a.positive_share)
    replies_q = prospects_q * a.reply_rate
    # People who reply stop receiving follow-ups; spread the reply rate evenly across steps.
    per_step_reply = a.reply_rate / a.sequence_steps
    emails_per_prospect = sum((1 - per_step_reply) ** k for k in range(a.sequence_steps))
    emails_q = prospects_q * emails_per_prospect
    w = WEEKS_PER_QUARTER
    daily = emails_q / w / 5
    return {
        "assumptions": asdict(a),
        "quarter": {"projects": a.projects_per_quarter, "calls": calls_q, "positive_replies": positive_q,
                    "replies": replies_q, "new_prospects": prospects_q, "emails_sent": emails_q},
        "week": {"projects": a.projects_per_quarter / w, "calls": calls_q / w, "positive_replies": positive_q / w,
                 "replies": replies_q / w, "new_prospects": prospects_q / w, "emails_sent": emails_q / w},
        "emails_per_prospect": emails_per_prospect,
        "emails_per_weekday": daily,
        "inboxes_needed": max(1, math.ceil(daily / a.per_inbox_daily_cap)),
        "overall_prospect_to_project": a.projects_per_quarter / prospects_q,
    }


def from_form(form) -> Assumptions:
    a = Assumptions()
    for field, default in asdict(a).items():
        raw = form.get(field)
        if raw in (None, ""):
            continue
        try:
            val = type(default)(float(raw)) if isinstance(default, int) else float(raw)
            if isinstance(default, float) and val > 1:  # accept "25" meaning 25%
                val = val / 100
            if val > 0:
                setattr(a, field, val)
        except ValueError:
            pass
    return a
