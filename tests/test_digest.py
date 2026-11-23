"""Daily digest, Gmail sender and alerts: fake HubSpot, fake SMTP, no network."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from scripts import send_alert, send_digest
from src.digest import DigestBuilder, github_failed_runs
from src.fake_hubspot import FakeHubSpot
from src.mailer import FakeMailer, GmailMailer, MailError

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 23, 6, 27, tzinfo=timezone.utc)


def seed(hs, name, stage, days_old=0, **props):
    stage_id = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == stage)
    rec = hs.post("/crm/v3/objects/deals", {"properties": {
        "dealname": name, "pipeline": "default", "dealstage": stage_id, **props}})
    if days_old:
        when = (NOW - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        hs.objects["deals"][rec["id"]]["properties"].update(hs_lastmodifieddate=when, createdate=when)
    return rec["id"]


def build(hs, runs=None):
    return DigestBuilder(hs, CONFIG, now=lambda: NOW, github=lambda since, tz: runs or []).build()


def test_digest_lists_ready_follow_ups_and_flags():
    hs = FakeHubSpot()
    low = seed(hs, "Growth Lead - B", "Ready for Review", fit_score="61", keyword_coverage="70")
    high = seed(hs, "GTM Engineer - A", "Ready for Review", fit_score="90", keyword_coverage="95.0")
    seed(hs, "RevOps - C", "Applied", days_old=6)
    seed(hs, "RevOps - D", "Applied", days_old=2)               # not due yet
    seed(hs, "Ops - E", "New", pipeline_error="NEEDS POST TEXT: paste the post")
    seed(hs, "Ops - F", "Archived", pipeline_error="AI ERROR: old")  # closed: not listed
    d = build(hs, runs=[{"name": "Import jobs", "url": "https://github.example/run/1", "when": "Mon 06:17"}])

    assert [x.id for x in d.ready] == [high, low] and d.ready[0].coverage == "95"
    assert d.ready[0].link == f"https://app.hubspot.com/contacts/123456/record/0-3/{high}"
    assert [x.name for x in d.follow_ups] == ["RevOps - C"] and d.follow_ups[0].days == 6
    assert [(x.name, x.flag, x.stage) for x in d.attention] == [("Ops - E", "NEEDS POST TEXT", "New")]
    assert d.counts["Ready for Review"] == 2 and d.counts["Applied"] == 2
    assert d.subject == ("Job digest Mon 23 Nov: 2 ready for review, 1 follow-up(s) due, "
                         "1 need you, 1 failed run(s)")
    text = d.text()
    assert "GTM Engineer - A (fit 90 | coverage 95%)" in text and "applied, no update for 6 days" in text
    assert "Import jobs (Mon 06:17)" in text
    assert "<a href=" in d.html() and "&lt;" not in d.html()


def test_html_escapes_deal_names_and_log_has_no_names():
    hs = FakeHubSpot()
    seed(hs, "Engineer <script> - X&Y", "Ready for Review", fit_score="80")
    d = build(hs)
    assert "<script>" not in d.html() and "&lt;script&gt;" in d.html()
    assert "Engineer" not in "\n".join(d.log_lines())


def test_empty_pipeline_and_github_problem_still_build():
    def broken(since, tz):
        raise ConnectionError("down")
    d = DigestBuilder(FakeHubSpot(), CONFIG, now=lambda: NOW, github=broken).build()
    assert d.ready_total == 0 and "- none" in d.text()
    assert d.notes and "Couldn't check GitHub" in d.notes[0]


def test_github_failed_runs_reads_the_api(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"workflow_runs": [{"name": "Process captures", "html_url": "https://gh/run/9",
                                       "created_at": "2026-11-23T05:47:10Z"}]}

    class Session:
        def get(self, url, params, headers, timeout):
            self.url, self.params, self.headers = url, params, headers
            return Resp()

    from zoneinfo import ZoneInfo
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    s = Session()
    runs = github_failed_runs(NOW - timedelta(hours=24), ZoneInfo("Africa/Lagos"), session=s)
    assert runs == [{"name": "Process captures", "url": "https://gh/run/9", "when": "Mon 06:47"}]
    assert s.url.endswith("/repos/owner/repo/actions/runs") and s.params["status"] == "failure"
    monkeypatch.delenv("GITHUB_TOKEN")
    assert github_failed_runs(NOW, ZoneInfo("UTC")) == []


class FakeSMTP:
    instances = []

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port, self.logins, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.logins.append((user, password))

    def send_message(self, msg):
        self.sent.append(msg)


def test_gmail_mailer_logs_in_and_sends_text_and_html():
    FakeSMTP.instances.clear()
    m = GmailMailer("sender@example.com", "abcd efgh ijkl mnop", "", smtp_factory=FakeSMTP)
    m.send("Subject", "plain", "<p>html</p>")
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 465)
    assert smtp.logins == [("sender@example.com", "abcdefghijklmnop")]   # spaces removed
    msg = smtp.sent[0]
    assert msg["To"] == "sender@example.com" and msg.is_multipart()      # defaults to the sender


def test_gmail_mailer_explains_missing_secrets_and_bad_login():
    with pytest.raises(MailError, match="GMAIL_APP_PASSWORD"):
        GmailMailer("sender@example.com", "", "")

    import smtplib

    class Refuse(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad")

    with pytest.raises(MailError, match="app password"):
        GmailMailer("s@example.com", "pw", "", smtp_factory=Refuse).send("s", "t")


def test_offline_script_and_alert_text(capsys):
    assert send_digest.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "Ready for review: 2 | follow-ups due: 1 | need you: 2" in out and "GTM Engineer - SampleCorp" in out
    subject, text = send_alert.alert_text("Import jobs", "https://github.com/o/r/actions/runs/1")
    assert "Import jobs" in subject and "actions/runs/1" in text


def test_fake_mailer_keeps_messages():
    m = FakeMailer()
    m.send("Hi", "text")
    assert m.sent[0]["Subject"] == "Hi"
