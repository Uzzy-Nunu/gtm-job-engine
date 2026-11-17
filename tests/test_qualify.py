"""Qualify step tests: made-up jobs, fake AI answers, fake HubSpot.

test_sample_jobs_score_as_expected is the PRD M4 acceptance check: sample jobs
score as expected and hard filters archive restricted roles.
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from src.fake_hubspot import FakeHubSpot
from src.llm import FakeProvider, LLMError
from src.cv_sections import qualify_profile
from src.qualify import SCHEMA, Qualifier, load_prompt
from src.scoring import score

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
SAMPLES = json.loads((ROOT / "tests" / "fixtures" / "qualify_samples.json").read_text(encoding="utf-8"))["samples"]
PROFILE = qualify_profile((ROOT / "tests" / "fixtures" / "sample_cv_profile.md").read_text(encoding="utf-8"))
BY_ID = {s["id"]: s for s in SAMPLES}


def answer(system, prompt, schema):
    sample_id = re.search(r"Ref (s\d+)\.", prompt).group(1)
    return BY_ID[sample_id]["ai"]


def seed(hs, sample_id=None, description=None, **props):
    stage_new = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == "New")
    body = {"dealname": props.pop("dealname", f"LinkedIn post by someone ({sample_id or 'x'})"),
            "pipeline": "default", "dealstage": stage_new, "job_source": "LinkedIn Post",
            "job_url": props.pop("job_url", f"https://www.linkedin.com/feed/update/urn:li:activity:{abs(hash(sample_id or description)) % 10**19}"),
            "description": description if description is not None else f"Ref {sample_id}. " + BY_ID[sample_id]["description"]}
    body.update(props)
    return hs.post("/crm/v3/objects/deals", {"properties": body})["id"]


def qualifier(hs, llm=None, **kw):
    return Qualifier(hs, llm or FakeProvider(answer), CONFIG, PROFILE, today=date(2026, 11, 18), **kw)


# --- PRD M4 acceptance ----------------------------------------------------------

@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: f"{s['id']}-{s['note'][:30]}")
def test_sample_jobs_score_as_expected(sample):
    hs = FakeHubSpot()
    deal_id = seed(hs, sample["id"])
    report = qualifier(hs).run()
    deal = hs.objects["deals"][deal_id]["properties"]
    expect = sample["expect"]
    assert hs.stage_label(deal["dealstage"]) == expect["status"]
    assert int(deal["fit_score"]) == expect["score"]
    if "name" in expect:
        assert deal["dealname"] == expect["name"]
    if "reason" in expect:
        assert expect["reason"] in deal["job_analysis"]
    assert report.outcomes[0].status == expect["status"]


def test_rubric_breakdown_matches_prd_weights():
    v = score(BY_ID["s1"]["ai"], CONFIG)
    assert dict(v.breakdown) == {"Remote worldwide": 30, "Title matches your target list": 25,
                                 "Skills and tools overlap (16/20)": 16, "Seniority: Mid": 15, "Salary listed": 10}


# --- deal updates ---------------------------------------------------------------

def test_qualified_deal_gets_analysis_company_and_remote_scope():
    hs = FakeHubSpot()
    deal_id = seed(hs, "s1")
    qualifier(hs).run()
    deal = hs.objects["deals"][deal_id]["properties"]
    assert deal["remote_scope"] == "Worldwide"
    analysis = deal["job_analysis"]
    assert analysis.startswith("Fit score: 96/100 (threshold 70) -> Qualified")
    assert "Gaps (don't add these to your CV unless true): SQL" in analysis
    companies = hs.all("companies")
    assert [c["properties"]["domain"] for c in companies] == ["samplecorp.example"]
    assert hs.associated("deals", deal_id, "companies") == [companies[0]["id"]]


def test_preview_mode_writes_nothing():
    hs = FakeHubSpot()
    deal_id = seed(hs, "s1")
    before = json.dumps(hs.objects, sort_keys=True)
    report = qualifier(hs, write=False).run()
    assert report.outcomes[0].status == "Qualified" and report.outcomes[0].score == 96
    assert json.dumps(hs.objects, sort_keys=True) == before
    assert not any(method in ("PATCH", "PUT") for method, _ in hs.calls)
    assert hs.stage_label(hs.objects["deals"][deal_id]["properties"]["dealstage"]) == "New"


def test_rerun_only_reads_new_deals():
    hs = FakeHubSpot()
    seed(hs, "s1")
    llm = FakeProvider(answer)
    qualifier(hs, llm).run()
    calls_after_first = llm.calls
    report = qualifier(hs, llm).run()
    assert report.outcomes == [] and llm.calls == calls_after_first


# --- privacy and inputs -----------------------------------------------------------

def test_contact_details_and_notes_never_reach_the_ai():
    hs = FakeHubSpot()
    seed(hs, description="Ref s1. " + BY_ID["s1"]["description"] +
         " Email jane@samplecorp.example or https://www.linkedin.com/in/jane-doe-123"
         "\n\n--- Notes from Peace ---\nmy friend Ada referred me")
    llm = FakeProvider(answer)
    qualifier(hs, llm).run()
    sent = llm.prompts[0]
    for private in ("jane@samplecorp.example", "linkedin.com/in/jane-doe-123", "Ada", "Notes from Peace"):
        assert private not in sent
    assert "CORE SKILLS" in sent and "HubSpot" in sent
    assert "alex.sample@example.com" not in sent      # CV contact block never sent


def test_prompt_and_schema_are_well_formed():
    system, user = load_prompt()
    assert system.startswith("You are a careful recruiting analyst")
    assert "remote_scope" in system and "{job_text}" in user and "{profile}" in user
    assert "{job_text}" not in system and "Used by src/qualify.py" not in system
    assert "poster" not in json.dumps(SCHEMA)          # poster details are never asked for


def test_deals_with_a_pipeline_error_are_skipped():
    hs = FakeHubSpot()
    seed(hs, "s1", pipeline_error="NEEDS POST TEXT: paste the post")
    llm = FakeProvider(answer)
    report = qualifier(hs, llm).run()
    assert report.outcomes[0].status == "skipped" and llm.calls == 0


class StubHttp:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def text(self, url, params=None):
        self.asked.append(url)
        return self.pages[url]


def test_short_text_is_filled_from_the_job_page():
    hs = FakeHubSpot()
    url = "https://careers.samplecorp.example/jobs/1"
    deal_id = seed(hs, description="Ref s1. GTM role", apply_url=url)
    http = StubHttp({url: "<h1>GTM Engineer</h1><p>" + BY_ID["s1"]["description"] + "</p>"})
    qualifier(hs, http=http, robots_ok=lambda u: True).run()
    assert http.asked == [url]
    assert hs.stage_label(hs.objects["deals"][deal_id]["properties"]["dealstage"]) == "Qualified"


def test_linkedin_and_robots_blocked_pages_are_never_fetched():
    hs = FakeHubSpot()
    seed(hs, description="Ref s1. short", apply_url="https://www.linkedin.com/jobs/view/123")
    seed(hs, description="Ref s1. short", apply_url="https://blocked.example/jobs/2", job_url="https://blocked.example/jobs/2")
    http = StubHttp({})
    report = qualifier(hs, http=http, robots_ok=lambda u: "blocked" not in u).run()
    assert http.asked == []
    assert [o.reason for o in report.outcomes] == ["job text too short"] * 2


def test_too_short_without_a_link_is_flagged_for_a_human():
    hs = FakeHubSpot()
    deal_id = seed(hs, description="Hiring!")
    qualifier(hs).run()
    assert hs.objects["deals"][deal_id]["properties"]["pipeline_error"].startswith("JOB TEXT TOO SHORT")


# --- AI failures ------------------------------------------------------------------

def test_ai_busy_stops_the_run_and_leaves_deals_for_later():
    hs = FakeHubSpot()
    seed(hs, "s1")
    seed(hs, "s5")

    def busy(system, prompt, schema):
        raise LLMError("Gemini 429: busy or rate-limited", retryable=True)

    llm = FakeProvider(busy, max_retries=0)
    report = qualifier(hs, llm).run()
    assert report.stopped and report.waiting == 2 and not report.ok
    assert all(hs.stage_label(d["properties"]["dealstage"]) == "New" for d in hs.all("deals"))


def test_bad_ai_answer_is_recorded_on_the_deal():
    hs = FakeHubSpot()
    deal_id = seed(hs, "s1")
    llm = FakeProvider(lambda s, p, sc: {"job_title": "x"})   # invalid twice
    report = qualifier(hs, llm).run()
    assert report.outcomes[0].status == "error"
    assert hs.objects["deals"][deal_id]["properties"]["pipeline_error"].startswith("AI ERROR")


def test_ai_call_cap_leaves_the_rest_for_the_next_run():
    hs = FakeHubSpot()
    for sid in ("s1", "s2", "s3"):
        seed(hs, sid)
    report = qualifier(hs).run(max_ai_calls=2)
    assert len(report.outcomes) == 2 and report.waiting == 1
