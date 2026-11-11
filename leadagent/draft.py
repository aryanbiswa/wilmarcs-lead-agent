"""Write a first-touch email (<120 words) from verified facts only, then check it in code."""
import re

from . import config
from .llm import generate_json

MAX_WORDS = 120
WILMARCS_FACTS = "Wilmarcs is a corporate and CSR film production house founded in Bengaluru in 2016, with offices in Dubai and Sydney."

SYSTEM = (
    "You write short, specific B2B cold emails in a friendly, plain Australian business tone: no hype, "
    "no exclamation marks, no 'I hope this finds you well'. You may only state facts about the prospect "
    "that appear in the numbered FACTS, and you cite each one inline as [n]."
)

PROMPT = """Write a first email from Wilmarcs to the {buyer} at {company}.

About Wilmarcs (no citation needed): {wilmarcs}
Film type to suggest: {film}

FACTS about {company} (the only things you may say about them; cite each as its own [n], e.g. [2][3]):
{facts}

Requirements:
- Body 60-85 words (a fixed sign-off and opt-out line of 14 words is added after it; total must stay under {max_words}).
- Open with the timing signal (fact [1]) and why it is a good moment for a {film}.
- Suggest exactly that one film type, with one concrete idea of what the film could show.
- One clear, low-effort ask: a 15-minute call in the next two weeks.
- Greeting "Hi there," (we don't have a name). Do not write a sign-off or opt-out line; they are added automatically.
- Do not open with "it is a great time/moment"; say plainly why their news made you write.
- Write numbers as digits and dates the Australian way: "15-minute", "26 October 2026", "1-4 April 2027" (never 2027-04-01, never spelled-out numbers).
- Do not invent numbers, dates, names or claims. No prices, revenue or share-price talk.
Return JSON: {{"subject": "under 8 words", "body": "..."}}
{feedback}"""


def _word_count(body: str) -> int:
    return len(re.sub(r"\[\d+\]", "", body).split())


def _check(draft: dict, facts: list[dict]) -> list[str]:
    problems = []
    body = draft.get("body", "")
    if not body or not draft.get("subject"):
        return ["missing subject or body"]
    wc = _word_count(body)
    if wc >= MAX_WORDS:
        problems.append(f"body is {wc} words; must be under {MAX_WORDS}")
    if stray := [b for b in re.findall(r"\[[^\]]*\]", body) if not re.fullmatch(r"\[\d+\]|\[Your name\]", b)]:
        problems.append(f"remove placeholder brackets {stray}; only [n] citations are allowed")
    if re.search(r"\b20\d\d-\d\d(-\d\d)?\b", body):
        problems.append("write dates in words (e.g. 1-4 April 2027), not as YYYY-MM-DD")
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", body)}
    if 1 not in cited:
        problems.append("timing signal is not cited as [1]")
    if bad := cited - set(range(1, len(facts) + 1)):
        problems.append(f"cites facts that don't exist: {sorted(bad)}")
    # Any number in the email must come from a fact (or Wilmarcs' own founding year).
    known = " ".join(f"{f['text']} {f.get('quote', '')}" for f in facts) + " 2016 15"
    for num in set(re.findall(r"\d[\d,.]*", re.sub(r"\[\d+\]", "", body))):
        if num.strip(".,") not in known:
            problems.append(f"number '{num}' is not in any sourced fact")
    return problems


SIGN_OFF = "[Your name]\nWilmarcs Sydney\n\nNot relevant? Reply 'no' and I won't follow up."


def tidy_body(body: str, facts: list[dict]) -> str:
    """Merge citations that point at the same URL, then add a fixed sign-off + opt-out (Spam Act)."""
    first_for_url = {}
    for i, f in enumerate(facts, start=1):
        first_for_url.setdefault(f["url"], i)

    def renumber(m):
        n = int(m.group(1))
        return f"[{first_for_url[facts[n - 1]['url']]}]" if 0 < n <= len(facts) else m.group(0)

    body = re.sub(r"\[(\d+(?:\s*,\s*\d+)+)\]", lambda m: "".join(f"[{n.strip()}]" for n in m.group(1).split(",")), body)
    body = re.sub(r"\[(\d+)\]", renumber, body)
    body = re.sub(r"(\[\d+\])(?:,?\s*\1)+", r"\1", body)  # "[2], [2]" -> "[2]"
    lines = [l for l in body.strip().splitlines()
             if not re.search(r"not relevant\?|opt.?out|unsubscribe|not interested|reply ['\"]?(stop|remove|no)\b|"
                              r"^\[your name\]|^wilmarcs( sydney)?$|^(cheers|regards|kind regards|thanks),?$|^\(.*\)$",
                              l.strip(), re.I)]
    return "\n".join(lines).rstrip() + "\n\n" + SIGN_OFF


def build_fact_list(facts: dict, signal: dict) -> list[dict]:
    items = [{"text": f"{signal['summary']} (date: {signal.get('date', 'n/a')})", "quote": signal["quote"], "url": signal["url"]}]
    # Size is used for scoring only; quoting a prospect's revenue back at them reads badly.
    for key, label in (("industry", "Industry"), ("city", "Based in")):
        if f := facts.get(key):
            items.append({"text": f"{label}: {f['value']}", "quote": f["quote"], "url": f["url"]})
    return items


def draft_email(company: str, facts: dict, signal: dict, buyer: str, use_cache: bool = True) -> dict:
    film = config.SIGNAL_PLAYBOOK[signal["type"]][0]
    fact_list = build_fact_list(facts, signal)
    facts_txt = "\n".join(f"[{i}] {f['text']} — evidence: \"{f['quote']}\"" for i, f in enumerate(fact_list, 1))
    feedback, problems, draft = "", [], {}
    for attempt in range(3):
        draft = generate_json(
            PROMPT.format(company=company, buyer=buyer.split(" (")[0], wilmarcs=WILMARCS_FACTS, film=film,
                          facts=facts_txt, max_words=MAX_WORDS, feedback=feedback),
            system=SYSTEM, use_cache=use_cache and attempt == 0, temperature=0.4,
        )
        draft["body"] = tidy_body(draft.get("body", ""), fact_list)
        problems = _check(draft, fact_list)
        if not problems:
            break
        feedback = "\nYour previous draft had problems, fix them:\n- " + "\n- ".join(problems)

    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", draft.get("body", ""))})
    sources = "\n".join(f"[{n}] {fact_list[n - 1]['url']}" for n in cited if 0 < n <= len(fact_list))
    return {
        "subject": draft.get("subject", ""),
        "body": draft.get("body", ""),
        "sources": sources,
        "word_count": _word_count(draft.get("body", "")),
        "film_type": film,
        "problems": problems,  # non-empty only if 3 attempts still failed the checks
        "attempts": attempt + 1,
    }
