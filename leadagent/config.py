"""Settings and the Wilmarcs-specific business rules the agent uses."""
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Tried in order; later models are used if an earlier one is unavailable (404) for this key.
GEMINI_MODELS = [m.strip() for m in os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite,gemini-flash-latest").split(",") if m.strip()]
LLM_MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("LLM_MIN_SECONDS_BETWEEN_CALLS", "4.5"))  # stay under free-tier RPM

TODAY = date.today()

HTTP_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 WilmarcsLeadResearch/1.0"
)
MAX_CHARS_PER_PAGE = 5000
MAX_SITE_PAGES = 6      # homepage + up to 5 internal pages
MAX_SEARCH_PAGES = 7    # external pages from search results

# Public pages only. These are either personal-data platforms the brief rules out
# (LinkedIn), paid data vendors, or encyclopaedias that are not primary sources.
BLOCKED_DOMAINS = (
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com",
    "youtube.com", "wikipedia.org", "grokipedia.com", "glassdoor.", "seek.com.au", "indeed.",
    "zoominfo.com", "rocketreach.co", "crunchbase.com", "pitchbook.com", "apollo.io",
    "bing.com/aclick", "duckduckgo.com/y.js", "google.com/aclk",
)

# Internal links worth reading on a company site, with a priority weight.
SITE_LINK_KEYWORDS = {
    "sustainab": 5, "esg": 5, "impact": 5, "news": 4, "media": 4, "press": 4,
    "announcement": 4, "event": 4, "conference": 5, "summit": 5, "expo": 4,
    "about": 3, "who-we-are": 3, "our-story": 3, "investor": 2, "report": 3, "anniversary": 4,
}

SEARCH_QUERIES = [
    "{name} conference summit {y} {y1}",
    "{name} sustainability impact report {y}",
    "{name} rebrand launch anniversary funding {y}",
    "{name} Australia {y1} event dates Sydney Melbourne",
]

SEGMENTS = ["ASX sustainability reporter", "Event & conference organiser"]

SIGNAL_TYPES = ["conference_or_summit", "sustainability_report", "rebrand", "funding_round", "anniversary", "product_launch"]

# Signal -> the Wilmarcs film type to suggest, and who usually buys it.
SIGNAL_PLAYBOOK = {
    "conference_or_summit":  ("event film (multicam coverage + same-week highlight/aftermovie)", "Events / Marketing lead"),
    "sustainability_report": ("CSR & impact film that brings the report's stories to life", "Head of Sustainability / Communications lead"),
    "rebrand":               ("brand film to launch the new identity", "Brand / Marketing lead"),
    "funding_round":         ("brand & corporate film for the next growth stage", "Marketing / Communications lead"),
    "anniversary":           ("corporate anniversary film (people, history, what's next)", "Communications / People & Culture lead"),
    "product_launch":        ("launch film with photography for the campaign", "Marketing / Brand lead"),
}
