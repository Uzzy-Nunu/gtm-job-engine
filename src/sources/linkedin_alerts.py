"""LinkedIn job-alert emails as a job source (PRD §10.1 IN-7).

LinkedIn emails Peace job alerts. This module reads those emails from Gmail
(IMAP, read-only, only messages from LinkedIn's job-alert senders) and pulls out
each job's title, company, location and LinkedIn job ID. It never opens LinkedIn.

For each alert job whose title and location pass the filters, it looks for the
same role on the company's own job board (Greenhouse, Lever or Ashby: the target
companies in config.yaml first, then the company name as a board token). If found,
the job comes in with the full description and the company's apply link. If not,
the deal is created with what the email says and flagged NEEDS POST TEXT, so Peace
can paste the description from LinkedIn herself.

Nothing from the email except job fields is kept. Logs show counts only.
"""

from __future__ import annotations

import email
import html
import imaplib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from src.job_filter import TitleFilter, _norm, looks_remote, region_ok
from src.sources import company_boards
from src.sources.base import JobPosting, html_to_text

IMAP_HOST = "imap.gmail.com"
SAMPLES_SHOWN = 15
DEFAULT_SENDERS = ["jobalerts-noreply@linkedin.com", "jobs-listings@linkedin.com"]
JOB_LINK = re.compile(r"https?://(?:[a-z]{2,3}\.)?(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)[^\s\"'<>)]*",
                      re.IGNORECASE)
NOISE = re.compile(
    r"^(view job|view all|see all|apply( now)?|easy apply|actively recruiting|promoted|new|top applicant|"
    r"be an early applicant|\d+\s+(applicants?|connections?|alumni|company alumni).*|.*\bconnections?\b.*works here.*|"
    r".*school alum.*|.*alumni work here.*|your job alert.*|jobs? (similar|you may be interested).*|"
    r"unsubscribe.*|manage (your )?alerts?.*|help|.*\bsearch\b.*|\d+ new jobs?.*|.*matches your preferences.*|"
    r"(hi|hello|dear) [^,]{1,40},?|.*linkedin corporation.*|this email was intended for.*|learn why.*)$",
    re.IGNORECASE)
MONEY = re.compile(r"[$€£₦]|\b\d+(\.\d+)?\s?[kK]\b|/yr|/hr|per (year|hour|annum)", re.IGNORECASE)


@dataclass
class AlertJob:
    job_id: str
    title: str
    company: str
    location: str
    received: datetime | None = None

    @property
    def url(self) -> str:
        return f"https://www.linkedin.com/jobs/view/{self.job_id}"


# --- parsing ---------------------------------------------------------------------------

def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = " ".join(raw.replace("‌", "").split()).strip(" -|•")
        if not line or len(line) > 140 or JOB_LINK.search(line) or line.startswith("http"):
            continue
        if NOISE.match(line) or (MONEY.search(line) and len(line) < 60 and "·" not in line):
            continue
        out.append(line)
    return out


def _card(job_id: str, lines: list[str], received) -> AlertJob | None:
    title = company = location = ""
    rest = []
    for line in lines:
        if "·" in line and not company:
            left, _, right = (p.strip() for p in line.partition("·"))
            company, location = left, right
        else:
            rest.append(line)
    if not rest:
        return None
    title = rest[0]
    if not company and len(rest) > 1:
        company = rest[1]
        location = rest[2] if len(rest) > 2 else ""
    elif company and not location and len(rest) > 1:
        location = rest[1]
    if not title or title.lower() == company.lower():
        return None
    return AlertJob(job_id, title, company, location, received)


def _cards_from_text(text: str, received) -> dict[str, AlertJob]:
    """Plain-text alerts: each job's lines come before its 'View job: <link>' line."""
    found: dict[str, AlertJob] = {}
    block: list[str] = []
    for raw in text.splitlines():
        m = JOB_LINK.search(raw)
        if m:
            job = _card(m.group(1), _clean_lines("\n".join(block[-6:])), received)
            if job and m.group(1) not in found:
                found[m.group(1)] = job
            block = []
        elif set(raw.strip()) <= {"-", "_", "="} and raw.strip():
            block = []
        else:
            block.append(raw)
    return found


def _cards_from_html(markup: str, received) -> dict[str, AlertJob]:
    """HTML alerts: a job's card is the markup from its first link to the next job's link."""
    markup = markup.replace("=\r\n", "").replace("=\n", "")
    starts: list[tuple[int, str]] = []
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"']", markup, re.IGNORECASE):
        link = JOB_LINK.search(html.unescape(m.group(1)))
        if link and (not starts or starts[-1][1] != link.group(1)):
            starts.append((m.start(), link.group(1)))
    found: dict[str, AlertJob] = {}
    for i, (pos, job_id) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(markup)
        chunk = re.sub(r"(?i)<br\s*/?>|</(p|div|td|tr|a|span|h\d|li|table)>", "\n", markup[pos:end])
        job = _card(job_id, _clean_lines(html_to_text(chunk)), received)
        if job and job_id not in found:
            found[job_id] = job
    return found


def parse_alert(raw: bytes) -> list[AlertJob]:
    msg = email.message_from_bytes(raw)
    try:
        received = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    except (TypeError, ValueError):
        received = None
    text_part = html_part = ""
    for part in msg.walk():
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if kind == "text/plain" and not text_part:
            text_part = body
        elif kind == "text/html" and not html_part:
            html_part = body
    jobs = _cards_from_html(html_part, received) if html_part else {}
    if text_part:
        for job_id, job in _cards_from_text(text_part, received).items():
            jobs.setdefault(job_id, job)
    return list(jobs.values())


# --- reading Gmail -------------------------------------------------------------------

class GmailAlerts:
    """Read-only IMAP access to LinkedIn job-alert emails in a Gmail account.

    Uses ALERTS_GMAIL_ADDRESS / ALERTS_GMAIL_APP_PASSWORD when the alerts arrive in a
    different Gmail account from the digest sender; otherwise GMAIL_ADDRESS /
    GMAIL_APP_PASSWORD (the digest's secrets)."""

    def __init__(self, address=None, app_password=None, imap_factory=imaplib.IMAP4_SSL):
        env = os.environ
        own = bool(env.get("ALERTS_GMAIL_ADDRESS", "").strip())
        default_address = env.get("ALERTS_GMAIL_ADDRESS", "") if own else env.get("GMAIL_ADDRESS", "")
        default_password = env.get("ALERTS_GMAIL_APP_PASSWORD", "") if own else env.get("GMAIL_APP_PASSWORD", "")
        self.address = (address if address is not None else default_address).strip()
        password = app_password if app_password is not None else default_password
        self.password = password.replace(" ", "").strip()
        self._imap = imap_factory

    @property
    def configured(self) -> bool:
        return bool(self.address and self.password)

    def fetch(self, senders: list[str], since: datetime, limit: int = 60) -> list[bytes]:
        box = self._imap(IMAP_HOST, 993)
        try:
            try:
                box.login(self.address, self.password)
            except imaplib.IMAP4.error:
                raise RuntimeError("Gmail refused the login for reading job alerts. Check GMAIL_APP_PASSWORD "
                                   "(an app password, not your normal password).") from None
            for folder in ('"[Gmail]/All Mail"', "INBOX"):
                status, _ = box.select(folder, readonly=True)
                if status == "OK":
                    break
            day = since.strftime("%d-%b-%Y")
            ids: list[bytes] = []
            for sender in senders:
                status, data = box.search(None, "SINCE", day, "FROM", f'"{sender}"')
                if status == "OK" and data and data[0]:
                    ids += data[0].split()
            messages = []
            for msg_id in sorted(set(ids), key=int)[-limit:]:
                status, data = box.fetch(msg_id, "(BODY.PEEK[])")   # PEEK: don't mark as read
                if status == "OK":
                    messages += [d[1] for d in data if isinstance(d, tuple)]
            return messages
        finally:
            try:
                box.logout()
            except Exception:  # noqa: BLE001
                pass


# --- finding the job on the company's own board ---------------------------------------

def _tokens(name: str) -> list[str]:
    base = re.sub(r"\b(inc|ltd|llc|gmbh|limited|corp|corporation|co|plc|sa|bv|ag|group|hq)\b\.?", "",
                  (name or "").lower())
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    joined, dashed = "".join(words), "-".join(words)
    return list(dict.fromkeys(t for t in (joined, dashed, words[0]) if len(t) >= 3))


def _same_title(a: str, b: str) -> bool:
    x, y = set(_norm(a).split()), set(_norm(b).split())
    if not x or not y:
        return False
    if _norm(a) == _norm(b):
        return True
    return len(x & y) / len(x | y) >= 0.75


class BoardFinder:
    """Find an alert's job on the company's own Greenhouse, Lever or Ashby board."""

    def __init__(self, http, config: dict):
        self.http = http
        self.known: dict[str, list[tuple[str, object]]] = {}
        for kind in ("greenhouse", "lever", "ashby"):
            for entry in (config.get("companies") or {}).get(kind) or []:
                b = company_boards.board_entry(entry)
                for key in filter(None, (b["name"], b["token"])):
                    self.known.setdefault(_norm(key), []).append((kind, entry))
        self._boards: dict[tuple[str, str], list[JobPosting] | None] = {}
        self.lookups = 0

    def _board(self, kind: str, entry) -> list[JobPosting] | None:
        token = company_boards.board_entry(entry)["token"]
        if (kind, token) not in self._boards:
            self.lookups += 1
            try:
                self._boards[(kind, token)] = getattr(company_boards, kind)(self.http, entry)
            except Exception:  # noqa: BLE001 - no board under this token
                self._boards[(kind, token)] = None
        return self._boards[(kind, token)]

    def find(self, job: AlertJob) -> JobPosting | None:
        candidates = list(self.known.get(_norm(job.company), []))
        if not candidates:
            candidates = [(kind, token) for token in _tokens(job.company)
                          for kind in ("greenhouse", "lever", "ashby")]
        for kind, entry in candidates:
            for posting in self._board(kind, entry) or []:
                if _same_title(posting.title, job.title):
                    return posting
            if self._boards.get((kind, company_boards.board_entry(entry)["token"])):
                break   # found the company's board; the role just isn't on it
        return None


# --- the source ---------------------------------------------------------------------

@dataclass
class AlertStats:
    emails: int = 0
    jobs: int = 0
    considered: int = 0
    found_on_board: int = 0
    needs_text: int = 0
    skipped_title: int = 0
    skipped_location: int = 0
    samples: list = None    # (reason, title, location) for the log: public job-posting text only

    def line(self) -> str:
        return (f"LinkedIn alerts: {self.emails} email(s), {self.jobs} job(s); {self.considered} passed title and "
                f"location; {self.found_on_board} found on the company's own board, {self.needs_text} need the "
                "description pasted")

    def detail_lines(self) -> list[str]:
        out = [f"  LinkedIn alert jobs skipped: title not on your lists {self.skipped_title}, "
               f"location not remote or not open to you {self.skipped_location}"]
        out += [f"  ~ {reason}: {title[:60]} | {location[:50] or 'no location'}"
                for reason, title, location in (self.samples or [])[:SAMPLES_SHOWN]]
        return out


def read_alerts(http, config: dict, mailbox, stats: AlertStats, now: datetime | None = None) -> list[JobPosting]:
    opts = config.get("linkedin_alerts") or {}
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=int(opts.get("days_back", 3)))
    raw = mailbox.fetch(opts.get("senders") or DEFAULT_SENDERS, since, int(opts.get("max_emails", 60)))
    stats.emails = len(raw)
    jobs: dict[str, AlertJob] = {}
    for message in raw:
        for job in parse_alert(message):
            jobs.setdefault(job.job_id, job)
    stats.jobs = len(jobs)

    titles = TitleFilter.from_config(config)
    eligible = config.get("eligible_regions") or []
    finder = BoardFinder(http, config)
    out = []
    for job in jobs.values():
        stats.samples = stats.samples or []
        if not titles.match(job.title):
            stats.skipped_title += 1
            stats.samples.append(("title", job.title, job.location))
            continue
        if not looks_remote(job.location) or not region_ok(job.location, eligible):
            stats.skipped_location += 1
            stats.samples.append(("location", job.title, job.location))
            continue
        stats.considered += 1
        posting = finder.find(job) if opts.get("find_on_company_boards", True) else None
        if posting:
            stats.found_on_board += 1
            posting.source = "LinkedIn Alert"
            posting.posted_at = posting.posted_at or job.received
            posting.text = f"Found via a LinkedIn job alert ({job.url}).\n\n{posting.text}"
            out.append(posting)
        else:
            stats.needs_text += 1
            out.append(JobPosting(source="LinkedIn Alert", url=job.url, title=job.title, company=job.company,
                                  location=job.location, posted_at=job.received, apply_url=job.url,
                                  needs_text=True))
    return out
