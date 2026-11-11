# Wilmarcs Lead Research Agent

Takes a CSV of Australian companies and returns a **researched, ranked review list**. Each row has industry, size band, city, likely buyer role, one recent timing signal, a 0–100 fit score with a one-line reason, and a first email draft (under 120 words) in which every fact links to its source page.
**Nothing is ever sent.** A person sets each row to Approve, Edit or Reject.

## Two ways to use it
**Web app (Lead Desk)** runs the whole assignment flow on one screen:
1. **Upload** the Task 2 CSV.
2. **Research (Task 1):** watch live progress. You get a ranked list in which each company expands to its facts, source links, evidence quote, score breakdown, draft and its own log. The full Log and Skipped tabs are there too, and you can download `review.xlsx`.
3. **Edit drafts (Task 3):** the tool's draft stays as *before*, you write the *after* with a live word count, and you note what changed and why. Approve, edit or reject each one, pick your 5 best and 2 for before/after, and download the edited-drafts sheet.
4. **Pilot plan:** a funnel calculator that works back from 6 projects a quarter to weekly emails, replies and calls. It also covers tools, spam prevention, the 3 Monday numbers and the top 2 risks, and downloads as a one-page plan.
5. **Hand-off:** approved drafts become an Instantly-ready CSV, or can be pushed by API into a **paused** campaign, with read-only tracking. The app never starts a campaign or sends email.

```bash
python app.py        # open http://localhost:5000
```
**Command line:** `python run.py input/companies.csv` produces the same research output with no UI.

## Stack choice (two lines)
Plain Python with direct calls to the Gemini free tier, DuckDuckGo search (free, no key) and `requests`/`trafilatura` for pages, with no agent framework.
The brief's hardest rule is "every fact links to its page, never guess", and plain code lets us *check* each quote against the page it came from, which a framework would hide.

## Run it
```bash
pip install -r requirements.txt
cp .env.example .env            # then paste a free key from https://aistudio.google.com/apikey
                                # optional: INSTANTLY_API_KEY=... INSTANTLY_CAMPAIGN_ID=... for the hand-off push
python run.py input/companies.csv            # writes output/review.xlsx (+ review.csv, run_log.jsonl)
python run.py input/companies.csv --limit 3  # quick test
python run.py --approved output/review.xlsx  # after review: lists rows marked Approve (still sends nothing)
```
Input CSV needs `company,website` columns (`name`/`url` also accepted). A full run of 21 companies takes about 3 minutes. Pages, searches and LLM answers are cached in `.cache/`, so reruns are fast and give the same results. Use `--no-cache` to re-research from scratch.

## How it works
```
CSV -> dedupe -> gather public sources -> LLM extracts facts + verbatim quotes -> code verifies quotes
    -> fixed-rule score -> LLM drafts email from verified facts only -> code checks draft -> review.xlsx
```
1. **Dedupe:** a row is skipped if its website domain or cleaned-up name ("Pty Ltd", "Group" and similar removed) matches one already seen. Skips go to the `Skipped` sheet.
2. **Sources (public only):** the homepage, plus up to 5 internal pages whose links mention news, media, sustainability, events and so on. Three DuckDuckGo searches per company (one per group of signal types in the brief), plus a news search limited to the past year. HTML and PDF are both read. LinkedIn, social media, Wikipedia and paid data sites are blocked.
3. **Excerpts:** long pages such as 100-page annual reports are cut down to the opening plus the passages around dates and signal words, so a date on page 40 isn't lost.
4. **Extraction:** Gemini returns each fact with a source ID and a **word-for-word quote**. A second call looks only for signals and red flags, to improve recall. Both calls go through the same verification.
5. **Verification:**
   - A fact is kept only if its quote is found on the cited page, using fuzzy matching to allow for small differences.
   - A near-miss quote is replaced by the real passage from the page, but only if that passage contains the signal's year.
   - The signal's date must appear in or near the quote. A stale signal (a report over 12 months old, or a past event) is rejected.
   - Anything that fails these checks shows as **"Not found (no source)"**.
6. **Score (fixed rules, shown on the "How scoring works" sheet):**

   | Part | Points | What earns them |
   |---|---|---|
   | Timing | 35 | How recent or upcoming the signal is |
   | Segment | 25 | A verified ASX listing, or a verified event organiser |
   | Size | 20 | 200–5,000 staff is the best fit |
   | City | 10 | Sydney 10, Melbourne 9 |
   | Buyer | 10 | The signal makes clear which team owns the budget |
   | Red flag | −20 | A sourced takeover, delisting or administration |

7. **Draft:**
   - The film type follows from the signal:
     - Summit → event film
     - Impact report → CSR or impact film
     - Rebrand → brand film
     - Anniversary → corporate anniversary film
     - Launch → launch film
   - Code checks each draft: under 120 words, signal cited as [1], only real citation numbers, and no number that isn't in a sourced fact. A failing draft is retried up to 3 times.
   - The same URL is always given the same citation number.
   - A fixed sign-off and opt-out line is added to every email, for the Spam Act.
8. **No signal means no draft.** The row says "needs human research" instead of guessing.

## Output: `output/review.xlsx`
| Sheet | What it holds |
|---|---|
| Review | One row per company, ranked by score. **Status** dropdown (Pending/Approve/Edit/Reject), reviewer notes, each fact next to its source link, the signal's evidence quote, the draft, and the draft's sources |
| Log | Every search and every URL tried (HTTP status, characters read, from cache or not, error), plus each fact that verification dropped and why |
| Skipped | Duplicate and invalid input rows |
| How scoring works | The scoring rules |

## Results on the Task 2 list (`output/review.xlsx`)
- **22 input rows:** 20 companies plus 2 deliberate test rows. The duplicate row was skipped, and the dead website was logged with score 0 and no crash.
- **15 of 21** researched companies have a verified, dated signal and a sourced draft. The other 6 say "needs human research" rather than guessing. They are mostly global event organisers whose Australian event runs on a separate website.
- **Red flags** found in public sources: Ingenia is in a takeover bidding war (Warburg Pincus vs Brookfield/Avid, Oct 2026), and its score drops by 20. Qube was found delisted after a takeover while the list was being built, and was replaced.
- **Task 3:** the 5 best drafts were edited by hand in the app, in `output/task3_edited_drafts.xlsx`. One was rejected because the tool misread "20-year history" as an anniversary.

## Assumptions
- **Segments:** ASX-listed companies that publish sustainability reports, and event or conference organisers. Both have public, dated signals.
- **Buyer role** is *inferred* from the signal type or segment, is labelled "(inferred)", and contains no personal data.
- **"Recent"** means a report released in the last 12 months, or an upcoming event.

## Known limits
- **Free-tier model:** Gemini 3.5 Flash-Lite. The stronger 3.8 Flash was about 6× slower and hit free-tier rate limits. Lite sometimes misses a signal that is there, and verification rejects it rather than letting a guess through. That is why some rows say "needs human research".
- **Bot protection:** some sites block automated reading (Qube, Bapcor). The tool logs the 403 and works from news coverage instead.
- **Event websites:** global organisers (IQPC, Terrapinn) run their Australian events on separate websites, which the tool may not find from the parent domain.
- **Dates:** checked to the year and month. The exact day should be confirmed by the reviewer.
- **Search:** DuckDuckGo results vary and are sometimes rate-limited. Searches are cached and retried, and a failed search is logged rather than crashing the run.

## With one more week
1. Add a second search source (the ASX announcements feed and event-listing sites such as ICC Sydney and MCEC) so signals don't depend on a single search engine.
2. Use a stronger model for the research step only, with a "second opinion" pass, and keep the fast model for drafts.
3. Build a small web review page that saves Approve/Edit/Reject decisions to a CRM and learns from them.

## Repo map
| Path | What it is |
|---|---|
| `app.py`, `templates/`, `static/` | The Lead Desk web app |
| `run.py` | Command-line entry point |
| `leadagent/` | Pipeline modules: inputs, fetch, research, extract (with verification), score, draft, report, funnel, instantly |
| `input/companies.csv` | The 20 Task 2 companies, plus 2 test rows (a duplicate and a dead website) |
| `output/review.xlsx` | The output file for the hand-in |
| `research/task2_final.csv` | The verified Task 2 target list |
| `docs/` | The Task 2 GTM plan and the Task 3 pilot plan, which are also Google Docs in the submission folder |
| `output/task3_edited_drafts.xlsx`, `output/instantly_leads.csv` | The Task 3 edits and the Instantly-ready export of approved drafts |

## AI tools used
- **Claude Code (Claude Opus):** planning, writing the code, debugging and test runs.
- **Gemini free tier:** inside the tool, for extracting facts and drafting emails.
