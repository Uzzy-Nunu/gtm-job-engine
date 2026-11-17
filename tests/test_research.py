"""Research step tests: made-up companies, fake websites, fake AI, fake HubSpot."""

import json
from pathlib import Path

import yaml

from src.fake_hubspot import FakeHubSpot
from src.llm import FakeProvider, LLMError
from src.research import SCHEMA, Researcher, brief_text, load_prompt, PROMPT_FILE

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

ANSWER = {
    "brief_bullets": ["SampleCorp sells revenue analytics software.", "Customers are B2B SaaS teams.",
                      "Series A, about 40 people."],
    "cover_letter_angle": "They are building their first outbound engine, which matches GTM engineering work.",
    "suggested_contact_titles": ["Head of Growth", "VP Revenue Operations"],
    "website_matches_company": True,
    "website_was_useful": True,
}
HOMEPAGE = ("<html><head><script>track()</script></head><body><h1>SampleCorp</h1>"
            "<p>Revenue analytics for B2B SaaS teams. Contact sales@samplecorp.example.</p>" + "<p>More.</p>" * 120
            + "</body></html>")


class StubHttp:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def text(self, url, params=None):
        self.asked.append(url)
        if url not in self.pages:
            raise RuntimeError("404")
        return self.pages[url]


def stage_id(hs, label):
    return next(s["id"] for s in hs.pipeline["stages"] if s["label"] == label)


def seed(hs, name="GTM Engineer - SampleCorp", score="80", domain="samplecorp.example", **props):
    deal = hs.post("/crm/v3/objects/deals", {"properties": {
        "dealname": name, "pipeline": "default", "dealstage": stage_id(hs, "Qualified"),
        "job_url": f"https://jobs.example/{name}", "fit_score": score,
        "description": "GTM Engineer at SampleCorp. Build outbound. Email jane@samplecorp.example",
        "job_analysis": "Fit score: 80/100 (threshold 70) -> Qualified", **props}})
    if domain is not None:
        company = hs.post("/crm/v3/objects/companies", {"properties": {"name": name.split(" - ")[-1], "domain": domain}})
        hs.put(f"/crm/v4/objects/deals/{deal['id']}/associations/default/companies/{company['id']}")
    return deal["id"]


def researcher(hs, llm=None, http=None, **kw):
    return Researcher(hs, llm or FakeProvider(lambda s, p, sc: ANSWER), CONFIG,
                      http=http if http is not None else StubHttp({"https://samplecorp.example": HOMEPAGE}),
                      robots_ok=kw.pop("robots_ok", lambda u: True), **kw)


def test_qualified_deal_gets_brief_and_moves_to_researched():
    hs = FakeHubSpot()
    deal_id = seed(hs)
    report = researcher(hs).run()
    deal = hs.objects["deals"][deal_id]["properties"]
    assert hs.stage_label(deal["dealstage"]) == "Researched"
    analysis = deal["job_analysis"]
    assert analysis.startswith("Fit score: 80/100")                 # qualify analysis kept
    assert "Company brief:\n- SampleCorp sells revenue analytics software." in analysis
    assert "Suggested contacts to look up (titles): Head of Growth, VP Revenue Operations" in analysis
    company = hs.all("companies")[0]["properties"]
    assert company["description"].startswith("SampleCorp sells revenue analytics software.")
    assert report.count("Researched") == 1 and report.ok


def test_website_and_job_text_are_redacted_and_scripts_dropped():
    hs = FakeHubSpot()
    seed(hs)
    llm = FakeProvider(lambda s, p, sc: ANSWER)
    researcher(hs, llm).run()
    sent = llm.prompts[0]
    assert "Revenue analytics for B2B SaaS teams" in sent
    for private in ("sales@samplecorp.example", "jane@samplecorp.example", "track()"):
        assert private not in sent


def test_short_homepage_also_reads_about_page():
    hs = FakeHubSpot()
    seed(hs)
    http = StubHttp({"https://samplecorp.example": "<p>Hi</p>",
                     "https://samplecorp.example/about": "<p>About SampleCorp</p>"})
    researcher(hs, http=http).run()
    assert http.asked == ["https://samplecorp.example", "https://samplecorp.example/about"]


def test_no_company_or_blocked_site_still_gets_a_brief_from_the_posting():
    hs = FakeHubSpot()
    no_company = seed(hs, name="Growth Lead - Demo Co", domain=None)
    blocked = seed(hs, name="RevOps Manager - Blocked Inc", domain="blocked.example")
    http = StubHttp({})
    answer = dict(ANSWER, website_was_useful=False)
    llm = FakeProvider(lambda s, p, sc: answer)
    report = researcher(hs, llm, http=http, robots_ok=lambda u: "blocked" not in u).run()
    assert not any("blocked" in u for u in http.asked)      # robots.txt said no
    assert any("demo" in u for u in http.asked)              # tried to find Demo Co's site, none verified
    assert any("(no website text available)" in prompt for prompt in llm.prompts)
    for deal_id in (no_company, blocked):
        deal = hs.objects["deals"][deal_id]["properties"]
        assert hs.stage_label(deal["dealstage"]) == "Researched"
        assert "job posting only" in deal["job_analysis"]
    assert all(o.note == "brief from job posting only" for o in report.outcomes)


def test_highest_fit_score_goes_first():
    hs = FakeHubSpot()
    seed(hs, name="Low - A", score="56", domain="a.example")
    seed(hs, name="High - B", score="100", domain="b.example")
    report = researcher(hs, http=StubHttp({})).run()
    assert [o.name for o in report.outcomes] == ["High - B", "Low - A"]


def test_existing_company_description_is_not_overwritten():
    hs = FakeHubSpot()
    seed(hs)
    company = hs.all("companies")[0]
    hs.patch(f"/crm/v3/objects/companies/{company['id']}", {"properties": {"description": "Written by Peace"}})
    researcher(hs).run()
    assert hs.all("companies")[0]["properties"]["description"] == "Written by Peace"


def test_preview_writes_nothing():
    hs = FakeHubSpot()
    seed(hs)
    before = json.dumps(hs.objects, sort_keys=True)
    report = researcher(hs, write=False).run()
    assert report.count("Researched") == 1
    assert json.dumps(hs.objects, sort_keys=True) == before


def test_rerun_after_moving_back_replaces_the_old_brief():
    hs = FakeHubSpot()
    deal_id = seed(hs)
    researcher(hs).run()
    hs.patch(f"/crm/v3/objects/deals/{deal_id}", {"properties": {"dealstage": stage_id(hs, "Qualified")}})
    researcher(hs).run()
    assert hs.objects["deals"][deal_id]["properties"]["job_analysis"].count("Company brief:") == 1


def test_skips_errors_and_stops_when_ai_is_busy():
    hs = FakeHubSpot()
    seed(hs, name="Flagged - X", domain=None, pipeline_error="AI ERROR: earlier")
    seed(hs, name="Fine - Y", domain=None)

    def busy(s, p, sc):
        raise LLMError("Gemini 429", retryable=True)

    report = researcher(hs, FakeProvider(busy, max_retries=0)).run()
    assert report.outcomes[0].status == "skipped" and report.stopped and report.waiting == 1


def test_poster_names_never_appear_in_the_log():
    hs = FakeHubSpot()
    seed(hs, name="LinkedIn post by Jane Doe (123456)", domain=None, pipeline_error="NEEDS POST TEXT: x")
    lines = "\n".join(researcher(hs).run().lines())
    assert "Jane Doe" not in lines and "LinkedIn post (#" in lines


def test_prompt_schema_and_brief_format():
    system, user = load_prompt(PROMPT_FILE)
    assert system.startswith("You are a sharp B2B market researcher")
    assert "{website}" in user and "{company}" in user and "{job_text}" in user
    assert "names" in system                     # titles only, never names
    assert SCHEMA["properties"]["suggested_contact_titles"]["maxItems"] == 3
    assert brief_text(dict(ANSWER, website_was_useful=False)).endswith("gave little to go on.)")
