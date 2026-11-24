"""Follow-up tasks (DG-2) and the weekly summary (DG-3): fake HubSpot, no network."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from scripts import send_digest, send_weekly
from src.fake_hubspot import FakeHubSpot
from src.followups import TASK_PREFIX, FollowUpTasks
from src.hubspot_client import HubSpotError
from src.weekly import WeeklyBuilder

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 23, 6, 27, tzinfo=timezone.utc)


def seed(hs, name, stage, days_old=0, **props):
    stage_id = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == stage)
    rec = hs.post("/crm/v3/objects/deals", {"properties": {
        "dealname": name, "pipeline": "default", "dealstage": stage_id, **props}})
    when = (NOW - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    hs.objects["deals"][rec["id"]]["properties"].update(hs_lastmodifieddate=when, createdate=when)
    return rec["id"]


def tasks_for(hs, deal_id):
    return [hs.objects["tasks"][t] for t in hs.associated("deals", deal_id, "tasks")]


# --- follow-up tasks ---------------------------------------------------------------

def test_quiet_applied_deals_get_one_task_and_reruns_add_none():
    hs = FakeHubSpot()
    quiet = seed(hs, "Growth Lead - Demo", "Applied", days_old=6)
    seed(hs, "Fresh - Demo", "Applied", days_old=2)
    seed(hs, "Old but not applied", "Researched", days_old=10)

    report = FollowUpTasks(hs, CONFIG, now=lambda: NOW).run(write=True)
    assert (report.due, report.created, report.already_open, report.errors) == (1, 1, 0, [])
    [task] = tasks_for(hs, quiet)
    p = task["properties"]
    assert p["hs_task_subject"] == f"{TASK_PREFIX} Growth Lead - Demo"
    assert p["hs_task_status"] == "NOT_STARTED" and p["hs_task_type"] == "TODO"
    assert "Followed Up" in p["hs_task_body"]

    again = FollowUpTasks(hs, CONFIG, now=lambda: NOW).run(write=True)
    assert (again.created, again.already_open) == (0, 1) and len(tasks_for(hs, quiet)) == 1
    assert again.task_deal_ids == {quiet}


def test_completed_task_allows_a_new_one_and_preview_writes_nothing():
    hs = FakeHubSpot()
    deal = seed(hs, "Growth Lead - Demo", "Applied", days_old=8)
    FollowUpTasks(hs, CONFIG, now=lambda: NOW).run(write=True)
    tasks_for(hs, deal)[0]["properties"]["hs_task_status"] = "COMPLETED"

    preview = FollowUpTasks(hs, CONFIG, now=lambda: NOW).run(write=False)
    assert preview.created == 1 and len(tasks_for(hs, deal)) == 1
    assert "would create" in preview.line(write=False)

    FollowUpTasks(hs, CONFIG, now=lambda: NOW).run(write=True)
    assert len(tasks_for(hs, deal)) == 2


def test_missing_scope_is_reported_once_not_per_deal():
    hs = FakeHubSpot()
    for i in range(3):
        seed(hs, f"Job {i}", "Applied", days_old=9)

    def refuse(path, json):
        if path == "/crm/v3/objects/tasks":
            raise HubSpotError(403, "This key is missing a scope", "MISSING_SCOPES", path)
        return FakeHubSpot.post(hs, path, json)

    hs.post = refuse
    report = FollowUpTasks(hs, CONFIG, now=lambda: NOW).run(write=True)
    assert report.due == 3 and report.created == 0 and len(report.errors) == 1
    assert "403" in report.errors[0]


def test_digest_script_marks_tasks_and_fails_loudly_on_task_errors(monkeypatch, capsys):
    assert send_digest.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "Follow-up tasks: 1 due, 1 created" in out and "task in HubSpot" in out

    def broken(self, write):
        from src.followups import FollowUpReport
        return FollowUpReport(due=1, errors=["HubSpot 403 MISSING_SCOPES on /crm/v3/objects/tasks: no scope"])

    monkeypatch.setattr(send_digest.FollowUpTasks, "run", broken)
    assert send_digest.main(["--offline"]) == 1
    out = capsys.readouterr().out
    assert "Couldn't add 1 follow-up task(s)" in out and "Follow-up tasks failed" in out


# --- weekly summary -----------------------------------------------------------------

def build_weekly(hs, runs=None):
    return WeeklyBuilder(hs, CONFIG, now=lambda: NOW, github=lambda since, tz: runs or []).build()


def test_weekly_funnel_numbers():
    hs = FakeHubSpot()
    seed(hs, "a", "New", days_old=1)
    seed(hs, "b", "Archived", days_old=2)
    seed(hs, "c", "Archived", days_old=3)
    seed(hs, "d", "Archived", days_old=3)
    seed(hs, "e", "Qualified", days_old=2)
    seed(hs, "f", "Ready for Review", days_old=4, keyword_coverage="90")
    seed(hs, "g", "Ready for Review", days_old=5, keyword_coverage="60",
         pipeline_error="TRUTH CHECK: 2 issue(s) in the drafts.")
    seed(hs, "h", "Applied", days_old=20, keyword_coverage="85", applied_date="2026-11-20")
    seed(hs, "i", "Interviewing", days_old=30, keyword_coverage="80", applied_date="2026-11-01")
    seed(hs, "j", "Rejected", days_old=30)

    w = build_weekly(hs, runs=[{"name": "x"}, {"name": "y"}])
    assert w.arrived == 7 and w.arrived_qualified == 3 and w.arrived_archived == 3 and w.arrived_waiting == 1
    assert w.applied == 1 and w.drafted == 4 and w.coverage_avg == 78.75 and w.coverage_at_target == 3
    assert w.truth_flagged == 1 and w.ever_applied == 3 and w.interviewing == 1 and w.failed_runs == 2
    text = w.text()
    assert "Qualified rate: 50% (3 of 6 processed" in text and "1 still waiting" in text
    assert "pass rate 75%" in text and "interview rate 33%" in text
    assert "Weekly job summary 16 Nov - 23 Nov: 1 applied, 7 new jobs" == w.subject


def test_weekly_reads_every_page_and_handles_an_empty_crm():
    hs = FakeHubSpot()
    for i in range(130):
        seed(hs, f"job {i}", "Archived", days_old=1)
    w = build_weekly(hs)
    assert w.arrived == 130 and w.arrived_archived == 130
    assert "Qualified rate: 0%" in w.text()

    empty = build_weekly(FakeHubSpot())
    assert empty.arrived == 0 and empty.coverage_avg is None and "n/a" in empty.text()
    assert "<" not in "".join(empty.log_lines())


def test_weekly_notes_missing_applied_dates_and_github_trouble():
    hs = FakeHubSpot()
    seed(hs, "h", "Applied", days_old=3)

    def boom(since, tz):
        raise RuntimeError("down")

    w = WeeklyBuilder(hs, CONFIG, now=lambda: NOW, github=boom).build()
    assert any("Applied Date" in n for n in w.notes)
    assert any("Couldn't check GitHub" in n for n in w.notes)


def test_weekly_offline_script(capsys):
    assert send_weekly.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "Weekly job summary" in out and "Sample job" not in out


# --- archive report -----------------------------------------------------------------

def test_archive_report_counts_reasons_and_rubric_parts(capsys):
    from scripts import archive_report
    assert archive_report.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "Fit score below the threshold: 1" in out and "Remote only in a region you can't work from: 1" in out
    assert "- Remote: 20.0" in out and "- Salary: 0.0" in out and "- USA: 1" in out
    assert "Demo" not in out   # company names stay out of the public log
