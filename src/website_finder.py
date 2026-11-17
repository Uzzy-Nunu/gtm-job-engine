"""Find a company's official website when the deal doesn't have one (PRD RE-1).

No paid search and no search-engine scraping. Candidates come from, in order:
  1. clues in the job text: email domains and company links (read by code; the
     raw text is never sent to the AI)
  2. the apply link, when it's on the company's own site
  3. one quick question to the AI ("what's the official website of ...?"),
     using only the company name and job title
  4. sensible guesses from the name (name.com, name.io, getname.com, ...)

Every candidate is verified by opening its homepage (robots.txt respected) and
checking the company's name appears and the page isn't a "domain for sale"
parking page. The first verified domain wins.
"""

from __future__ import annotations

import re
import unicodedata

from src.llm import LLMError
from src.sources.base import html_to_text
from src.urls import URLError, company_domain, find_external_job_links

FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
             "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com", "gmx.com", "mail.com",
             "yandex.com", "zoho.com", "example.com"}
NOT_COMPANY = ("linkedin.com", "lnkd.in", "twitter.com", "x.com", "facebook.com", "instagram.com",
               "youtube.com", "youtu.be", "tiktok.com", "github.com", "medium.com", "substack.com",
               "google.com", "forms.gle", "bit.ly", "calendly.com", "notion.site", "typeform.com",
               "wa.me", "t.me")
PARKED = ("domain is for sale", "buy this domain", "this domain may be for sale", "domain for sale",
          "parked free", "parkingcrew", "sedo.com", "hugedomains", "dan.com", "afternic", "godaddy.com/domain")
SUFFIXES = ("inc", "inc.", "ltd", "ltd.", "llc", "gmbh", "limited", "corp", "corporation", "co", "co.",
            "plc", "sa", "bv", "ag", "technologies", "technology", "labs", "hq", "group", "holdings")
EMAIL_DOMAIN = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

ASK_SCHEMA = {
    "type": "object",
    "required": ["domain"],
    "properties": {"domain": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
}
ASK_SYSTEM = ("You identify companies' official websites. Answer with the bare domain only "
              "(for example samplecorp.com), or null if you aren't confident. Never guess wildly.")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def name_words(company: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", _ascii(company).lower())
    while words and words[-1] in {s.strip(".") for s in SUFFIXES}:
        words.pop()
    return words


def clean_domain(value: str | None) -> str | None:
    if not value:
        return None
    d = re.sub(r"^https?://", "", str(value).strip().lower()).split("/")[0].split("?")[0]
    d = d[4:] if d.startswith("www.") else d
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d):
        return None
    if d in FREE_MAIL or any(d == s or d.endswith("." + s) for s in NOT_COMPANY):
        return None
    return d


def from_text(raw_text: str) -> list[str]:
    """Domains hinted at in the job text: email addresses, then company links."""
    found: list[str] = []
    for d in EMAIL_DOMAIN.findall(raw_text or ""):
        d = clean_domain(d)
        if d and d not in found:
            found.append(d)
    for url in find_external_job_links(raw_text or ""):
        try:
            d = clean_domain(company_domain(url))
        except URLError:
            d = None
        if d and d not in found:
            found.append(d)
    return found


def guesses(company: str) -> list[str]:
    words = name_words(company)
    if not words:
        return []
    joined = "".join(words)
    stems = [joined] + (["-".join(words)] if len(words) > 1 else [])
    out = []
    for stem in stems:
        out += [f"{stem}.com", f"{stem}.io", f"{stem}.ai", f"{stem}.co"]
    out += [f"get{joined}.com", f"{joined}hq.com", f"try{joined}.com"]
    return out


def name_appears(company: str, page_text: str) -> bool:
    """All distinctive words of the company name appear on the page."""
    words = [w for w in name_words(company) if len(w) >= 3] or name_words(company)
    text = re.sub(r"[^a-z0-9]+", " ", _ascii(page_text).lower())
    squashed = text.replace(" ", "")
    return bool(words) and all(f" {w} " in f" {text} " or w in squashed for w in words)


def looks_parked(page_text: str) -> bool:
    lowered = page_text.lower()
    return len(lowered.strip()) < 40 or any(p in lowered for p in PARKED)


# Words too common in job posts and websites to say what a business does.
STOPWORDS = set("""
about above after again against also always among another apply applying based because been before
being below between both build building can come company could currently does doing during each
every experience first from full further have having help here hiring home into join just know
learn like looking make more most much must need next only other our ours over part people
please position really remote role roles same should some such team teams than that their them
then there these they thing things this those through time today together under until using very
want were what when where which while will with within work working world would year years your
yours youre we're you'll we'll you've anywhere global worldwide great best new free more info contact
privacy policy terms cookies cookie rights reserved login sign signup started careers jobs blog
""".split())
MIN_JOB_WORDS = 25    # below this, the job text is too short to judge topics
MIN_SHARED = 3        # topic words a guessed site must share with the job text


def topic_words(text: str, exclude: list[str] | None = None) -> set[str]:
    words = set(re.findall(r"[a-z][a-z0-9]{3,}", _ascii(text or "").lower()))
    return words - STOPWORDS - set(exclude or [])


def same_topic(job_text: str, page_text: str, company: str) -> bool:
    """True when a guessed site talks about the same things as the job post
    (an AI-for-sales startup and a perfume brand share almost no words).
    Short job texts can't be judged, so they pass and the AI check decides."""
    job = topic_words(job_text, name_words(company))
    if len(job) < MIN_JOB_WORDS:
        return True
    return len(job & topic_words(page_text, name_words(company))) >= MIN_SHARED


class WebsiteFinder:
    def __init__(self, http, llm=None, robots_ok=None, max_checks: int = 10):
        self.http = http
        self.llm = llm
        self.robots_ok = robots_ok or (lambda url: True)
        self.max_checks = max_checks
        self.checked: list[str] = []
        self.off_topic: list[str] = []

    def verify(self, domain: str, company: str) -> str | None:
        """Homepage text if the domain is the company's live site, else None."""
        url = f"https://{domain}"
        try:
            if not self.robots_ok(url):
                return None
            text = html_to_text(self.http.text(url))
        except Exception:  # noqa: BLE001 - unreachable, refused or not a site
            return None
        if looks_parked(text) or not name_appears(company, text):
            return None
        return text

    def ask_ai(self, company: str, job_title: str) -> str | None:
        if self.llm is None:
            return None
        try:
            answer = self.llm.generate_json(
                system=ASK_SYSTEM, schema=ASK_SCHEMA, role="fast",
                prompt=f"Company: {company}\nIt is hiring for: {job_title}\nWhat is its official website domain?")
        except LLMError:
            return None
        return clean_domain(answer.get("domain"))

    def find(self, company: str, job_title: str = "", raw_text: str = "",
             apply_url: str | None = None) -> tuple[str | None, str | None, str]:
        """(domain, homepage text, how it was found) or (None, None, reason)."""
        self.checked = []  # each company gets its own budget of checks
        if not name_words(company):
            return None, None, "no company name"
        stages = [("job text", lambda: from_text(raw_text)),
                  ("apply link", lambda: [d for d in [clean_domain(_safe_domain(apply_url))] if d]),
                  ("AI suggestion", lambda: [d for d in [self.ask_ai(company, job_title)] if d]),
                  ("name guess", lambda: guesses(company))]
        weak = {"AI suggestion", "name guess"}  # need the topic check too
        self.off_topic: list[str] = []
        for how, candidates in stages:
            for domain in candidates():
                if domain in self.checked or len(self.checked) >= self.max_checks:
                    continue
                self.checked.append(domain)
                text = self.verify(domain, company)
                if not text:
                    continue
                if how in weak and not same_topic(raw_text, text, company):
                    self.off_topic.append(domain)   # same name, different business: keep looking
                    continue
                return domain, text, how
        return None, None, "no website could be verified"


def _safe_domain(url):
    try:
        return company_domain(url) if url else None
    except URLError:
        return None
