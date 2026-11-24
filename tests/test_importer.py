"""Job-board import tests using made-up board data (tests/fixtures/boards)."""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.fake_hubspot import FakeHubSpot
from src.importer import run_import
from src.sources.base import SourceError, html_to_text

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("import_jobs", ROOT / "scripts" / "import_jobs.py")
import_jobs = importlib.util.module_from_spec(spec)
sys.modules["import_jobs"] = import_jobs
spec.loader.exec_module(import_jobs)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def config(**overrides):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    import_jobs.apply_offline_settings(cfg)
    cfg.update(overrides)
    return cfg


def run(cfg=None, hs=None, http=None):
    hs = hs or FakeHubSpot()
    report = run_import(cfg or config(), hs, http or import_jobs.OfflineHttp(), now=NOW)
    return report, hs


def test_import_creates_matching_jobs_and_skips_the_rest():
    report, hs = run()
    assert report.ok, report.errors
    names = sorted(d["properties"]["dealname"] for d in hs.all("deals"))
    assert names == sorted([
        "Senior GTM Engineer - SampleCorp",
        "Marketing Automation Specialist - Demo Co",
        "AI Operations Lead - Fictional AI",
        "Growth Operations Manager - Placeholder Inc",
        "Marketing Operations Manager - Demo Systems",
        "Founder's Associate (Growth) - Fictional Labs",
        "Revenue Operations Lead - Sample Remote Co",
        "Demand Generation Manager - Fictional Growth",
    ])
    assert report.duplicates == 1           # same SampleCorp job on Greenhouse and RemoteOK
    assert report.skipped["title"] == 4      # Account Executive, Business Development Manager, Sales Manager, Lifecycle Marketing Manager
    assert report.skipped["location"] == 5   # Remote - US, London Office, hybrid Berlin, 2x US-only
    assert report.skipped["too old"] == 1
    assert "Ashby fictional" in report.fetched and report.fetched["Ashby fictional"] == 1  # unlisted dropped


def test_deal_details_from_boards():
    _, hs = run()
    deals = {d["properties"]["dealname"]: d["properties"] for d in hs.all("deals")}
    gh = deals["Senior GTM Engineer - SampleCorp"]
    assert gh["job_source"] in ("Greenhouse", "RemoteOK")
    ai = deals["AI Operations Lead - Fictional AI"]
    assert ai["job_source"] == "Ashby"
    assert ai["apply_url"] == "https://jobs.ashbyhq.com/fictional/ab-1/application"
    assert "Location: Remote, Africa" in ai["description"]
    assert "Salary: $60K - $80K" in ai["description"]
    assert hs.stage_label(ai["dealstage"]) == "New"
    domains = sorted(c["properties"].get("domain") or "" for c in hs.all("companies"))
    assert "fictional.example" in domains


def test_remotive_and_jobicy_details():
    _, hs = run()
    deals = {d["properties"]["dealname"]: d["properties"] for d in hs.all("deals")}
    rem = deals["Revenue Operations Lead - Sample Remote Co"]
    assert rem["job_source"] == "Remotive"
    assert rem["job_url"].startswith("https://remotive.com/remote-jobs/")  # link back (Remotive terms)
    assert "Source: Remotive" in rem["description"]
    job = deals["Demand Generation Manager - Fictional Growth"]
    assert job["job_source"] == "Jobicy"
    assert "Salary: EUR 50,000-60,000 per year" in job["description"]


def test_explore_titles_are_imported_last_and_labelled():
    cfg = config(explore_titles=["Lifecycle Marketing", "Sales Manager"])
    report, hs = run(cfg)
    assert report.matched_by_list["explore"] == 1        # Lifecycle Marketing Manager; the Sales Manager role is US-only
    assert report.created_by_list["explore"] == 1
    assert report.created[-1].endswith("[explore]")      # after all target and adjacent roles
    deal = next(d["properties"] for d in hs.all("deals")
                if d["properties"]["dealname"].startswith("Lifecycle Marketing Manager"))
    assert "Matched title list: explore" in deal["description"]
    assert any(line.startswith("Matches by title list:") for line in report.lines())


def test_explore_titles_never_crowd_out_core_roles():
    report, _ = run(config(daily_import_cap=3, explore_titles=["Lifecycle Marketing"]))
    assert report.created_by_list["explore"] == 0
    assert report.created_by_list["target"] == 3


def test_explore_titles_are_added_to_himalayas_searches():
    seen = []

    class RecordingHttp(import_jobs.OfflineHttp):
        def json(self, url, params=None):
            if "himalayas" in url:
                seen.append(params["q"])
            return super().json(url, params)

    run(config(explore_titles=["Lifecycle Marketing", "sample"]), http=RecordingHttp())
    assert seen == ["sample", "Lifecycle Marketing"]   # no duplicate search for "sample"


def test_rerun_same_day_creates_nothing_new():
    report1, hs = run()
    report2, _ = run(hs=hs)
    assert len(report2.created) == 0
    assert report2.duplicates == len(report1.created) + report1.duplicates
    assert len(hs.all("deals")) == len(report1.created)


def test_daily_cap_is_respected_across_runs():
    report1, hs = run(config(daily_import_cap=3))
    assert len(report1.created) == 3
    assert report1.not_imported_cap > 0
    report2, _ = run(config(daily_import_cap=3), hs=hs)
    assert report2.already_today == 3
    assert report2.created == []


def test_target_titles_are_imported_before_adjacent_ones():
    report, _ = run(config(daily_import_cap=2))
    assert all(("Engineer" in n or "Automation" in n or "Growth Operations" in n) for n in report.created)


class BrokenGreenhouse(import_jobs.OfflineHttp):
    def json(self, url, params=None):
        if "greenhouse" in url:
            raise SourceError("Not found (check the board token)")
        return super().json(url, params)


def test_one_broken_board_does_not_stop_the_others():
    report, hs = run(http=BrokenGreenhouse())
    assert not report.ok
    assert any("Greenhouse samplecorp" in e for e in report.errors)
    assert len(hs.all("deals")) >= 5


def test_html_to_text_handles_escaped_html_and_lists():
    text = html_to_text("&lt;p&gt;Build &lt;strong&gt;outbound&lt;/strong&gt;.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Clay&lt;/li&gt;&lt;/ul&gt;")
    assert text == "Build outbound.\n\n- Clay"


def test_offline_dry_run_script(capsys):
    assert import_jobs.main(["--dry-run", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "New deals:" in out


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers, self.content = status, headers or {}, b"{}"

    def raise_for_status(self):
        pass

    def json(self):
        return {}


def test_http_waits_between_requests_and_honours_retry_after():
    from src.sources.base import Http
    slept = []
    clock = iter([0.0, 0.1, 0.2, 10.0, 10.1, 20.0])
    http = Http(sleep=slept.append, clock=lambda: next(clock), min_interval=1.5)
    responses = iter([_Resp(200), _Resp(429, {"Retry-After": "7"}), _Resp(200)])
    http.session.get = lambda *a, **k: next(responses)
    http.get("https://site.example/a")
    http.get("https://site.example/b")
    assert slept[0] == pytest.approx(1.4)   # gap to the previous call on the same site
    assert 7 in slept                        # Retry-After respected


def test_http_gives_up_with_clear_rate_limit_message():
    from src.sources.base import Http
    http = Http(sleep=lambda s: None, retries=1)
    http.session.get = lambda *a, **k: _Resp(429)
    with pytest.raises(SourceError, match="rate limited"):
        http.get("https://site.example/a")


def test_html_to_text_skips_scripts_and_styles():
    page = ("<html><head><title>T</title><style>.a{color:red}</style></head><body>"
            "<script>var tracking = 1;</script><h1>SampleCorp</h1><p>We sell CRM tools.</p>"
            "<noscript>enable js</noscript></body></html>")
    text = html_to_text(page)
    assert "SampleCorp" in text and "We sell CRM tools." in text
    for junk in ("color:red", "tracking", "enable js"):
        assert junk not in text


def test_near_misses_list_remote_recent_jobs_skipped_only_for_title():
    from src.importer import ImportReport, select
    from src.sources.base import JobPosting
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)
    job = lambda title, loc="Remote", age=1: JobPosting(  # noqa: E731
        source="Other", url=f"https://example.com/{title}-{loc}-{age}".replace(" ", "-"), title=title,
        company="Demo", location=loc, posted_at=now.replace(day=24 - age))
    report = ImportReport()
    select([job("Lifecycle Marketing Manager"), job("Lifecycle Marketing Manager", age=2),
            job("Account Executive", loc="Remote - US only"), job("Office Manager", age=20),
            job("GTM Engineer")], config(explore_titles=[]), report, now=now)
    assert report.kept == 1 and dict(report.near_misses) == {"Lifecycle Marketing Manager": 2}
    assert "  ? Lifecycle Marketing Manager (2)" in report.lines()
