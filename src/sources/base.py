"""Shared pieces for job-board readers (PRD §10.1 IN-3).

Every reader returns a list of JobPosting in the same shape, so the import
runner doesn't care where a job came from. Readers only use public,
documented job feeds. None of them touch LinkedIn.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser

import requests

USER_AGENT = "gtm-job-engine/1.0 (personal job search tool; +https://github.com/Uzzy-Nunu/gtm-job-engine)"


@dataclass
class JobPosting:
    source: str                     # value for the Job Source property
    url: str                        # the job's own page (duplicate key)
    title: str
    company: str
    text: str = ""                  # plain-text description
    location: str = ""              # as the board states it
    workplace_type: str = ""        # remote / hybrid / on-site, if given
    apply_url: str | None = None
    company_website: str | None = None
    posted_at: datetime | None = None
    salary: str | None = None


class SourceError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(markup: str | None) -> str:
    """HTML (or HTML-escaped HTML, as Greenhouse sends) to readable plain text."""
    if not markup:
        return ""
    if "&lt;" in markup and "<" not in markup:
        markup = html.unescape(markup)
    parser = _TextExtractor()
    parser.feed(markup)
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def from_epoch(value) -> datetime | None:
    if value in (None, ""):
        return None
    value = float(value)
    if value > 10_000_000_000:  # milliseconds
        value /= 1000
    return datetime.fromtimestamp(value, tz=timezone.utc)


def from_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def salary_text(low, high, currency="USD", period="year") -> str | None:
    if not low and not high:
        return None
    fmt = lambda v: f"{int(v):,}"  # noqa: E731
    span = f"{fmt(low)}-{fmt(high)}" if low and high else fmt(low or high)
    return f"{currency or ''} {span} per {period or 'year'}".strip()


class Http:
    """Polite GET: clear User-Agent, a minimum gap between requests to the
    same site, honours Retry-After on 429, and retries a couple of times."""

    MAX_WAIT = 60  # seconds; never sleep longer than this for one retry

    def __init__(self, timeout: int = 30, retries: int = 2, pause: float = 2.0,
                 min_interval: float = 1.5, sleep=time.sleep, clock=time.monotonic):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.retries = retries
        self.pause = pause
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: dict[str, float] = {}

    def _wait_turn(self, url: str) -> None:
        host = url.split("/")[2] if "//" in url else url
        last = self._last.get(host)
        if last is not None:
            gap = self.min_interval - (self._clock() - last)
            if gap > 0:
                self._sleep(gap)
        self._last[host] = self._clock()

    def _retry_wait(self, resp, attempt: int) -> float:
        header = resp.headers.get("Retry-After") if resp is not None else None
        try:
            wait = float(header) if header else self.pause * (2 ** attempt)
        except ValueError:
            wait = self.pause * (2 ** attempt)
        return min(wait, self.MAX_WAIT)

    def get(self, url: str, params=None) -> requests.Response:
        last = None
        for attempt in range(self.retries + 1):
            try:
                self._wait_turn(url)
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = SourceError(f"{resp.status_code} from {url}"
                                       + (" (rate limited: the site asked us to slow down)"
                                          if resp.status_code == 429 else ""))
                    if attempt < self.retries:
                        self._sleep(self._retry_wait(resp, attempt))
                    continue
                if resp.status_code == 404:
                    raise SourceError(f"Not found (check the board token): {url}")
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last = SourceError(f"Could not reach {url}: {e}")
                if attempt < self.retries:
                    self._sleep(self.pause * (2 ** attempt))
        raise last

    def json(self, url: str, params=None):
        return self.get(url, params).json()

    def text(self, url: str, params=None) -> str:
        return self.get(url, params).text
