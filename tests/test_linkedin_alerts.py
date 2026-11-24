"""LinkedIn job-alert emails: parsing, board matching and import. Made-up emails only."""

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import yaml

from src.fake_hubspot import FakeHubSpot
from src.importer import run_import
from src.sources import linkedin_alerts as la
from src.sources.base import SourceError
from src.urls import linkedin_job_url, normalise_url

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc)

TEXT_ALERT = """Hi Alex,

Your job alert for GTM Engineer
3 new jobs match your preferences.

GTM Engineer
Sample Analytics
Remote
Actively recruiting
View job: https://www.linkedin.com/comm/jobs/view/4100000001/?trackingId=abc&refId=xyz

---------------------------------------------------------

Senior RevOps Manager
Demo Payments
EMEA (Remote)
$90K/yr - $110K/yr
View job: https://www.linkedin.com/comm/jobs/view/4100000002/?trackingId=def

---------------------------------------------------------

Office Manager
Example Ltd
Lagos, Nigeria (On-site)
View job: https://www.linkedin.com/comm/jobs/view/4100000003/

Unsubscribe: https://www.linkedin.com/comm/jobs/alerts?x=1
This email was intended for Alex Sample (Growth person)
"""

HTML_ALERT = """<html><body><p>Hi Alex,</p>
<table><tr><td>
<a href="https://www.linkedin.com/comm/jobs/view/4200000001/?trackingId=a&amp;refId=b"><img alt="Fictional AI"></a>
<a href="https://www.linkedin.com/comm/jobs/view/4200000001/?trackingId=a">Marketing Automation Specialist</a>
<p>Fictional AI &middot; United States (Remote)</p>
<p>2 connections work here</p>
</td></tr><tr><td>
<a href="https://www.linkedin.com/comm/jobs/view/4200000002/?x=1">AI Automation Lead</a>
<p>Placeholder Labs &middot; Worldwide (Remote)</p>
<a href="https://www.linkedin.com/comm/jobs/view/4200000002/?x=1">View job</a>
</td></tr></table>
<a href="https://www.linkedin.com/comm/jobs/alerts">Manage alerts</a></body></html>"""


def message(text=None, markup=None, sender="jobalerts-noreply@linkedin.com") -> bytes:
    msg = EmailMessage()
    msg["From"] = f"LinkedIn Job Alerts <{sender}>"
    msg["To"] = "alex@example.com"
    msg["Subject"] = "New jobs for you"
    msg["Date"] = "Mon, 23 Nov 2026 08:00:00 +0000"
    msg.set_content(text or "See the HTML version.")
    if markup:
        msg.add_alternative(markup, subtype="html")
    return msg.as_bytes()


class FakeMailbox:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def fetch(self, senders, since, limit=60):
        self.calls.append((tuple(senders), since))
        return list(self.messages)


class BoardHttp:
    """Answers for one Ashby board ('placeholderlabs'); every other board is missing."""

    def __init__(self):
        self.urls = []

    def json(self, url, params=None):
        self.urls.append(url)
        if url.endswith("/job-board/placeholderlabs"):
            return {"jobs": [{"title": "AI Automation Lead", "jobUrl": "https://jobs.ashbyhq.com/placeholderlabs/1",
                              "location": "Remote", "isRemote": True, "descriptionPlain": "Lead our AI automation.",
                              "publishedAt": "2026-11-20T00:00:00Z"}]}
        raise SourceError("404")


def config(**overrides):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["companies"] = {}
    cfg["public_feeds"] = {}
    cfg["extra_feeds"] = []
    cfg.update(overrides)
    return cfg


# --- parsing --------------------------------------------------------------------------

def test_plain_text_alert_is_parsed_without_noise_or_personal_lines():
    jobs = {j.job_id: j for j in la.parse_alert(message(TEXT_ALERT))}
    assert set(jobs) == {"4100000001", "4100000002", "4100000003"}
    j = jobs["4100000001"]
    assert (j.title, j.company, j.location) == ("GTM Engineer", "Sample Analytics", "Remote")
    assert jobs["4100000002"].location == "EMEA (Remote)"
    assert j.url == "https://www.linkedin.com/jobs/view/4100000001"
    assert j.received == datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


def test_html_alert_is_parsed_with_company_and_location_from_the_dot_line():
    jobs = {j.job_id: j for j in la.parse_alert(message(markup=HTML_ALERT))}
    assert set(jobs) == {"4200000001", "4200000002"}
    assert (jobs["4200000002"].title, jobs["4200000002"].company, jobs["4200000002"].location) == (
        "AI Automation Lead", "Placeholder Labs", "Worldwide (Remote)")
    assert jobs["4200000001"].title == "Marketing Automation Specialist"


def test_linkedin_job_links_get_one_canonical_key():
    url = "https://www.linkedin.com/comm/jobs/view/4100000001/?trackingId=abc"
    assert linkedin_job_url(url) == normalise_url(url) == "https://www.linkedin.com/jobs/view/4100000001"
    assert linkedin_job_url("https://example.com/jobs/view/4100000001") is None


# --- import ---------------------------------------------------------------------------

def test_alert_jobs_are_filtered_matched_to_boards_and_flagged_when_not_found():
    hs, http = FakeHubSpot(), BoardHttp()
    box = FakeMailbox([message(TEXT_ALERT), message(markup=HTML_ALERT)])
    report = run_import(config(), hs, http, now=NOW, mailbox=box)

    stats = report.alerts
    # US-only and on-site jobs are dropped by the filters before any board lookup
    assert (stats.emails, stats.jobs, stats.considered, stats.found_on_board, stats.needs_text) == (2, 5, 3, 1, 2)
    deals = {d["properties"]["job_url"]: d["properties"] for d in hs.all("deals")}
    found = deals["https://jobs.ashbyhq.com/placeholderlabs/1"]
    assert found["job_source"] == "LinkedIn Alert" and "Lead our AI automation." in found["description"]
    assert not found.get("pipeline_error")
    waiting = deals["https://www.linkedin.com/jobs/view/4100000001"]
    assert waiting["pipeline_error"].startswith("NEEDS POST TEXT")
    assert waiting["apply_url"] == "https://www.linkedin.com/jobs/view/4100000001"
    assert len(deals) == 3
    assert not any("linkedin.com" in u for u in http.urls)   # never opens LinkedIn
    assert "LinkedIn alerts: 2 email(s), 5 job(s); 3 passed" in "\n".join(report.lines())

    again = run_import(config(), hs, BoardHttp(), now=NOW, mailbox=box)
    assert again.duplicates == 3 and len(hs.all("deals")) == 3
    # a re-read never clears the flag with the email's own header text
    refreshed = {d["properties"]["job_url"]: d["properties"] for d in hs.all("deals")}
    assert refreshed["https://www.linkedin.com/jobs/view/4100000001"]["pipeline_error"].startswith("NEEDS POST TEXT")


def test_alerts_off_or_no_mailbox_reads_nothing():
    box = FakeMailbox([message(TEXT_ALERT)])
    report = run_import(config(linkedin_alerts={"enabled": False}), FakeHubSpot(), BoardHttp(), now=NOW, mailbox=box)
    assert report.alerts is None and box.calls == []
    report = run_import(config(), FakeHubSpot(), BoardHttp(), now=NOW, mailbox=None)
    assert report.alerts is None


def test_known_target_company_board_is_used_before_guessing():
    cfg = config(companies={"ashby": [{"token": "placeholderlabs", "name": "Placeholder Labs"}]})
    http = BoardHttp()
    finder = la.BoardFinder(http, cfg)
    job = la.AlertJob("1", "AI Automation Lead", "Placeholder Labs", "Remote")
    assert finder.find(job).url == "https://jobs.ashbyhq.com/placeholderlabs/1"
    assert http.urls == ["https://api.ashbyhq.com/posting-api/job-board/placeholderlabs"]


# --- Gmail ------------------------------------------------------------------------------

class FakeIMAP:
    def __init__(self, host, port, fail_login=False):
        self.log = [("connect", host, port)]
        self.fail_login = fail_login

    def login(self, user, password):
        import imaplib
        if self.fail_login:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        self.log.append(("login", user, password))

    def select(self, folder, readonly=False):
        self.log.append(("select", folder, readonly))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.log.append(("search",) + criteria)
        return "OK", [b"7 9"]

    def fetch(self, msg_id, parts):
        self.log.append(("fetch", msg_id, parts))
        return "OK", [(b"header", message(TEXT_ALERT)), b")"]

    def logout(self):
        self.log.append(("logout",))


def test_gmail_reader_is_read_only_and_explains_a_bad_login():
    import pytest
    made = []

    def factory(host, port):
        made.append(FakeIMAP(host, port))
        return made[-1]

    box = la.GmailAlerts("me@example.com", "abcd efgh ijkl mnop", imap_factory=factory)
    raw = box.fetch(["jobalerts-noreply@linkedin.com"], NOW)
    log = made[0].log
    assert ("login", "me@example.com", "abcdefghijklmnop") in log
    assert ("select", '"[Gmail]/All Mail"', True) in log
    assert ("search", "SINCE", "24-Nov-2026", "FROM", '"jobalerts-noreply@linkedin.com"') in log
    assert all(entry[2] == "(BODY.PEEK[])" for entry in log if entry[0] == "fetch")
    assert len(raw) == 2 and log[-1] == ("logout",)

    bad = la.GmailAlerts("me@example.com", "x", imap_factory=lambda h, p: FakeIMAP(h, p, fail_login=True))
    with pytest.raises(RuntimeError, match="app password"):
        bad.fetch(["jobalerts-noreply@linkedin.com"], NOW)


def test_alerts_can_use_their_own_gmail_account(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "sender@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "sender-pass")
    assert la.GmailAlerts().address == "sender@example.com"
    monkeypatch.setenv("ALERTS_GMAIL_ADDRESS", "alerts@example.com")
    monkeypatch.setenv("ALERTS_GMAIL_APP_PASSWORD", "alerts pass")
    box = la.GmailAlerts()
    assert (box.address, box.password, box.configured) == ("alerts@example.com", "alertspass", True)


def test_busy_ai_stop_is_a_warning_but_errors_fail(capsys):
    from src.llm import exit_code
    assert exit_code(False, None) == 0
    assert exit_code(False, "AI busy") == 0 and "::warning::" in capsys.readouterr().out
    assert exit_code(True, "AI busy") == 1
