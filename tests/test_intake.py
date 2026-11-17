"""Intake tests against the in-memory FakeHubSpot (made-up data only).

The first three tests are the Milestone 3 acceptance criteria (PRD §17).
"""

from datetime import datetime, timedelta, timezone

from src.fake_hubspot import FakeHubSpot
from src.hubspot_client import HubSpotError
from src.hubspot_schema import NEEDS_POST_TEXT
from src.intake import Intake, Submission

POST = "https://www.linkedin.com/posts/jane-doe-123_hiring-gtm-activity-7390000000000000001-AbCd?utm_source=share"
SAME_POST_OTHER_STYLE = "https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001/"
POST_TEXT = "We're hiring a GTM Engineer, remote worldwide. Python, Clay, HubSpot."


def setup():
    hs = FakeHubSpot()
    return hs, Intake(hs)


# --- PRD M3 acceptance criteria ----------------------------------------

def test_capture_creates_one_deal_and_linked_poster_contact():
    hs, intake = setup()
    result = intake.submit(Submission(url=POST, text=POST_TEXT))

    assert result.status == "created"
    deals, contacts = hs.all("deals"), hs.all("contacts")
    assert len(deals) == 1 and len(contacts) == 1
    deal = deals[0]["properties"]
    assert deal["job_url"] == "https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001"
    assert deal["job_source"] == "LinkedIn Post"
    assert hs.stage_label(deal["dealstage"]) == "New"
    assert deal["description"] == POST_TEXT
    assert not deal.get("pipeline_error")

    contact = contacts[0]["properties"]
    assert contact["hs_linkedin_url"] == "https://www.linkedin.com/in/jane-doe-123"
    assert contact["firstname"] == "Jane"
    assert contact["lastname"] == "Doe (unconfirmed)"
    assert hs.associated("deals", result.deal_id, "contacts") == [contacts[0]["id"]]


def test_repeat_capture_is_flagged_duplicate():
    hs, intake = setup()
    first = intake.submit(Submission(url=POST, text=POST_TEXT))
    again = intake.submit(Submission(url=SAME_POST_OTHER_STYLE, text=POST_TEXT))

    assert again.status == "duplicate"
    assert again.deal_id == first.deal_id
    assert len(hs.all("deals")) == 1
    assert len(hs.all("contacts")) == 1


def test_url_only_is_flagged_needs_post_text_then_fixed_by_resubmitting():
    hs, intake = setup()
    result = intake.submit(Submission(url=POST))
    assert result.status == "created"
    assert NEEDS_POST_TEXT in result.flags
    assert hs.all("deals")[0]["properties"]["pipeline_error"].startswith(NEEDS_POST_TEXT)

    later = intake.submit(Submission(url=POST, text=POST_TEXT))
    assert later.status == "updated"
    deal = hs.all("deals")[0]["properties"]
    assert deal["description"] == POST_TEXT
    assert deal["pipeline_error"] == ""
    assert len(hs.all("deals")) == 1


# --- other intake rules -------------------------------------------------

def test_same_poster_again_reuses_contact():
    hs, intake = setup()
    intake.submit(Submission(url=POST, text=POST_TEXT))
    other_post = "https://www.linkedin.com/posts/jane-doe-123_revops-activity-7395555555555555555-Xx"
    intake.submit(Submission(url=other_post, text="Another remote role."))
    assert len(hs.all("deals")) == 2
    assert len(hs.all("contacts")) == 1


def test_external_job_link_in_post_becomes_apply_url_and_company():
    hs, intake = setup()
    text = POST_TEXT + " Apply here: https://careers.samplecorp.example/jobs/42?utm_source=linkedin"
    result = intake.submit(Submission(url=POST, text=text))
    deal = hs.all("deals")[0]["properties"]
    assert deal["apply_url"] == "https://careers.samplecorp.example/jobs/42"
    assert NEEDS_POST_TEXT not in result.flags
    companies = hs.all("companies")
    assert [c["properties"]["domain"] for c in companies] == ["samplecorp.example"]
    assert hs.associated("deals", result.deal_id, "companies") == [companies[0]["id"]]
    assert hs.associated("contacts", hs.all("contacts")[0]["id"], "companies") == [companies[0]["id"]]


def test_url_only_with_external_link_is_not_flagged():
    _, intake = setup()
    result = intake.submit(Submission(url=POST, text="https://jobs.lever.co/demo-co/abc"))
    assert NEEDS_POST_TEXT not in result.flags


def test_post_link_without_author_creates_no_contact():
    hs, intake = setup()
    result = intake.submit(Submission(url=SAME_POST_OTHER_STYLE, text=POST_TEXT))
    assert result.status == "created"
    assert hs.all("contacts") == []
    assert "unknown poster" in hs.all("deals")[0]["properties"]["dealname"]


def test_board_job_names_deal_and_reuses_company_by_domain():
    hs, intake = setup()
    a = intake.submit(Submission(url="https://boards.greenhouse.io/samplecorp/jobs/1?gh_src=x",
                                 text="Job one", title="GTM Engineer", company="SampleCorp",
                                 company_website="https://www.samplecorp.example"))
    b = intake.submit(Submission(url="https://boards.greenhouse.io/samplecorp/jobs/2",
                                 text="Job two", title="Growth Engineer", company="SampleCorp",
                                 company_website="https://samplecorp.example"))
    assert a.status == b.status == "created"
    names = sorted(d["properties"]["dealname"] for d in hs.all("deals"))
    assert names == ["GTM Engineer - SampleCorp", "Growth Engineer - SampleCorp"]
    assert hs.all("deals")[0]["properties"]["job_source"] == "Greenhouse"
    assert len(hs.all("companies")) == 1


def test_cross_source_duplicate_within_window_is_skipped():
    hs, intake = setup()
    intake.submit(Submission(url="https://boards.greenhouse.io/samplecorp/jobs/1",
                             text="x", title="GTM Engineer", company="SampleCorp"))
    dup = intake.submit(Submission(url="https://remoteok.com/remote-jobs/999",
                                   text="x", title="GTM Engineer", company="SampleCorp"))
    assert dup.status == "duplicate"
    assert len(hs.all("deals")) == 1


def test_cross_source_twin_older_than_window_is_allowed():
    hs = FakeHubSpot()
    later = datetime.now(timezone.utc) + timedelta(days=30)
    Intake(hs).submit(Submission(url="https://boards.greenhouse.io/s/jobs/1", text="x",
                                 title="GTM Engineer", company="SampleCorp"))
    result = Intake(hs, now=lambda: later).submit(Submission(
        url="https://remoteok.com/remote-jobs/999", text="x", title="GTM Engineer", company="SampleCorp"))
    assert result.status == "created"


def test_company_site_link_without_text_is_not_flagged():
    hs, intake = setup()
    result = intake.submit(Submission(url="https://careers.demo.example/jobs/7"))
    assert result.status == "created"
    deal = hs.all("deals")[0]["properties"]
    assert deal["job_source"] == "Company Site"
    assert deal["apply_url"] == "https://careers.demo.example/jobs/7"
    assert not result.flags


def test_title_without_company_gets_placeholder_name():
    hs, intake = setup()
    intake.submit(Submission(url="https://board.example/job/seo-lead", text="x", title="SEO Lead"))
    assert hs.all("deals")[0]["properties"]["dealname"] == "SEO Lead - company TBC"


def test_notes_are_kept_with_the_post_text():
    hs, intake = setup()
    intake.submit(Submission(url=POST, text=POST_TEXT, notes="Saw this via a friend"))
    assert "Notes from Peace ---\nSaw this via a friend" in hs.all("deals")[0]["properties"]["description"]


def test_bad_link_returns_a_clear_error_and_creates_nothing():
    hs, intake = setup()
    result = intake.submit(Submission(url="https://lnkd.in/abc"))
    assert result.status == "error"
    assert "Copy link to post" in result.message
    assert hs.all("deals") == []


def test_race_between_search_and_create_counts_as_duplicate():
    hs, intake = setup()
    real_post = hs.post

    def racing_post(path, json):
        if path == "/crm/v3/objects/deals":
            raise HubSpotError(409, "exists", "CONFLICT", path)
        return real_post(path, json)

    hs.post = racing_post
    assert intake.submit(Submission(url=POST, text=POST_TEXT)).status == "duplicate"


def test_missing_pipeline_is_a_loud_error():
    hs = FakeHubSpot()
    hs.pipeline["label"] = "Sales Pipeline"
    result = Intake(hs).submit(Submission(url=POST, text=POST_TEXT))
    assert result.status == "error"
    assert "Run Setup HubSpot" in result.message
