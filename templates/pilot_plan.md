# Wilmarcs Sydney: 30-day outbound pilot

**Goal:** a repeatable path to the Sydney team's capacity of **{{ a.projects_per_quarter }} new projects a quarter** (AUD 8,000–40,000 each), using timing-signal outreach instead of referrals alone.

## Targets: working backwards
| Stage | Rate assumed | Per quarter | Per week |
|---|---|---:|---:|
| New prospects emailed | | {{ f.quarter.new_prospects|n1 }} | {{ f.week.new_prospects|n1 }} |
| Emails sent (3-step sequence) | × {{ '%.2f'|format(f.emails_per_prospect) }} | {{ f.quarter.emails_sent|n1 }} | {{ f.week.emails_sent|n1 }} |
| Replies | {{ a.reply_rate|pct }} of prospects | {{ f.quarter.replies|n1 }} | {{ f.week.replies|n1 }} |
| Interested replies | {{ a.positive_share|pct }} of replies | {{ f.quarter.positive_replies|n1 }} | {{ f.week.positive_replies|n1 }} |
| Discovery calls | {{ a.positive_reply_to_call|pct }} of interested | {{ f.quarter.calls|n1 }} | {{ f.week.calls|n1 }} |
| **New projects** | {{ a.call_to_project|pct }} of calls | **{{ f.quarter.projects|n1 }}** | {{ f.week.projects|n1 }} |

{{ a.projects_per_quarter }} ÷ {{ a.call_to_project|pct }} = {{ f.quarter.calls|n1 }} calls → ÷ {{ a.positive_reply_to_call|pct }} = {{ f.quarter.positive_replies|n1 }} interested replies → ÷ ({{ a.reply_rate|pct }} × {{ a.positive_share|pct }}) = {{ f.quarter.new_prospects|n1 }} prospects over 13 weeks. That is ~{{ f.emails_per_weekday|round|int }} emails a weekday, so {{ f.inboxes_needed }} warmed inboxes at ≤30 a day.

## Tools
- **Lead research agent (this repo):** a weekly run on ~{{ (f.week.new_prospects * 1.5)|round|int }} companies. About 2 in 3 return a sourced, dated signal and a draft.
- **Instantly:** sending, warm-up, inbox rotation, reply tracking and unsubscribes. **HubSpot CRM (free):** the pipeline. **Calendly:** 15-minute calls on Sydney time.

**Keeping emails out of spam:**

1. Use a separate sending domain with SPF, DKIM and DMARC, warm it up for 2–3 weeks, and send no more than 30 a day per inbox.
2. Write in plain text with no images or attachments and at most one link, and turn open tracking off on the first touch.
3. Use only verified, role-relevant published addresses, keep bounces under 2%, and honour unsubscribes immediately.

## Every Monday: 3 numbers
1. **New prospects emailed** (target {{ f.week.new_prospects|round|int }} a week)
2. **Interested-reply rate** (target {{ (a.reply_rate * a.positive_share)|pct }})
3. **Discovery calls booked** (target {{ '%.1f'|format(f.week.calls) }} a week)

## Top 2 risks
1. **Not enough signal-qualified companies.** {{ f.week.new_prospects|round|int }} a week is more than two segments in two cities produce with fresh signals. *Response:* add a third segment (universities or NFPs), add ASX announcements and venue calendars (ICC Sydney, MCEC) as sources, and re-check "no signal" companies monthly.
2. **Replies land below 4%**, from deliverability problems or being seen as an offshore studio. *Response:* check inbox placement first, A/B test subject lines, lead with the Sydney office and 2 local case studies, and add a LinkedIn touch before the follow-up.

## 30-day timeline
- **Week 1:** domain and inbox set-up and warm-up, CRM stages, a research run on 150 companies, and 5 hand-edited drafts approved.
- **Week 2:** first 50 sends to the strongest fits only (score ≥ 75), with replies read daily.
- **Weeks 3–4:** ramp up to the weekly target, then review the 3 numbers and reset the assumptions with the real rates.

## 5 best drafts (edited by hand)
{% for d in top5 %}- **{{ d.company }}** ({{ d.signal_date }}): "{{ d.subject }}"
{% else %}- (select 5 on the Edit drafts page)
{% endfor %}
{% for d in showcase %}
### Before / after: {{ d.company }}
**Before (tool):**
```
{{ d.original_body }}
```
**After (edited):**
```
{{ d.body }}
```
**What changed and why:** {{ d.note }}
{% endfor %}
