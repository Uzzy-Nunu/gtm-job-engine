"""Website finder tests: made-up companies and pages, no real network."""

import pytest

from src.fake_hubspot import FakeHubSpot
from src.llm import FakeProvider
from src.website_finder import (WebsiteFinder, clean_domain, from_text, guesses,
                                looks_parked, name_appears)


class StubHttp:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def text(self, url, params=None):
        self.asked.append(url)
        if url not in self.pages:
            raise RuntimeError("unreachable")
        return self.pages[url]


SITE = "<html><body><h1>Skylar Labs</h1><p>Skylar builds AI copilots for revenue teams.</p></body></html>"


def test_clues_in_the_job_text_come_first():
    text = ("Apply via jobs@skylar.example or email the founder at jane@gmail.com. "
            "Details: https://www.skylar.example/careers/gtm?utm_source=li and https://boards.greenhouse.io/skylar/jobs/1 "
            "and https://www.linkedin.com/company/skylar")
    assert from_text(text) == ["skylar.example"]


def test_found_in_job_text_and_verified():
    finder = WebsiteFinder(StubHttp({"https://skylar.example": SITE}))
    domain, page, how = finder.find("Skylar", "GTM Engineer", raw_text="Send CVs to talent@skylar.example")
    assert (domain, how) == ("skylar.example", "job text")
    assert "AI copilots" in page


def test_ai_suggestion_is_used_when_the_text_has_no_clues():
    llm = FakeProvider(lambda s, p, sc: {"domain": "https://www.skylarhq.example/"})
    finder = WebsiteFinder(StubHttp({"https://skylarhq.example": SITE}), llm)
    domain, _, how = finder.find("Skylar", "GTM Engineer", raw_text="We're hiring!")
    assert (domain, how) == ("skylarhq.example", "AI suggestion")
    assert "Skylar" in llm.prompts[0] and "GTM Engineer" in llm.prompts[0]


def test_name_guesses_are_the_last_resort():
    http = StubHttp({"https://skylar.ai": SITE})
    llm = FakeProvider(lambda s, p, sc: {"domain": None})
    domain, _, how = WebsiteFinder(http, llm).find("Skylar Inc.", "GTM Engineer")
    assert (domain, how) == ("skylar.ai", "name guess")
    assert http.asked[:3] == ["https://skylar.com", "https://skylar.io", "https://skylar.ai"]


def test_wrong_company_or_parked_page_is_rejected():
    pages = {"https://skylar.com": "<h1>Welcome to Bob's Bakery</h1><p>Fresh bread daily in Leeds.</p>",
             "https://skylar.io": "<p>This domain is for sale! Buy this domain today. Skylar</p>"}
    domain, _, how = WebsiteFinder(StubHttp(pages)).find("Skylar", "GTM Engineer")
    assert domain is None and how == "no website could be verified"


def test_robots_blocked_sites_are_never_opened():
    http = StubHttp({"https://skylar.com": SITE})
    domain, _, _ = WebsiteFinder(http, robots_ok=lambda u: False).find("Skylar")
    assert domain is None and http.asked == []


def test_checks_are_capped_per_company():
    http = StubHttp({})
    finder = WebsiteFinder(http, max_checks=3)
    finder.find("Skylar")
    finder.find("Demo Co")
    assert len(http.asked) == 6


@pytest.mark.parametrize("company,page,expected", [
    ("Skylar", "Skylar - AI for revenue teams", True),
    ("Skylar Labs Inc", "SKYLAR LABS | Home", True),
    ("Demo Systems", "DemoSystems platform", True),
    ("Skylar", "Bob's Bakery", False),
    ("Café Nova", "Cafe Nova roasters", True),
])
def test_name_appears(company, page, expected):
    assert name_appears(company, page) is expected


def test_helpers():
    assert clean_domain("https://www.SampleCorp.example/about?x=1") == "samplecorp.example"
    assert clean_domain("gmail.com") is None and clean_domain("linkedin.com") is None
    assert clean_domain("not a domain") is None
    assert guesses("Demo Systems GmbH")[:2] == ["demosystems.com", "demosystems.io"]
    assert "demo-systems.com" in guesses("Demo Systems")
    assert looks_parked("Buy this domain") and not looks_parked("SampleCorp builds revenue analytics tools.")


def test_research_saves_the_found_domain_to_the_company():
    from tests.test_research import ANSWER, CONFIG, seed
    from src.research import Researcher
    hs = FakeHubSpot()
    deal_id = seed(hs, name="GTM Engineer - Skylar", domain=None,
                   description="We're hiring a GTM Engineer. Apply: talent@skylar.example")
    http = StubHttp({"https://skylar.example": SITE * 10})
    report = Researcher(hs, FakeProvider(lambda s, p, sc: ANSWER), CONFIG, http=http,
                        robots_ok=lambda u: True).run()
    companies = hs.all("companies")
    assert [c["properties"]["domain"] for c in companies] == ["skylar.example"]
    assert hs.associated("deals", deal_id, "companies") == [companies[0]["id"]]
    assert report.outcomes[0].note == "website found via job text: skylar.example"


def test_preview_finds_but_does_not_save():
    from tests.test_research import ANSWER, CONFIG, seed
    from src.research import Researcher
    hs = FakeHubSpot()
    seed(hs, name="GTM Engineer - Skylar", domain=None, description="Apply: talent@skylar.example")
    report = Researcher(hs, FakeProvider(lambda s, p, sc: ANSWER), CONFIG, write=False,
                        http=StubHttp({"https://skylar.example": SITE * 10}), robots_ok=lambda u: True).run()
    assert hs.all("companies") == []
    assert "skylar.example" in report.outcomes[0].note


def test_research_rejects_a_same_named_different_company():
    from tests.test_research import ANSWER, CONFIG, seed
    from src.research import Researcher
    hs = FakeHubSpot()
    deal_id = seed(hs, name="GTM Engineer - Skylar", domain=None, description="AI copilots for sales teams.")
    perfume = "<h1>Skylar</h1><p>Clean, hypoallergenic fragrances.</p>" * 20
    answer = dict(ANSWER, website_matches_company=False, website_was_useful=False)
    report = Researcher(hs, FakeProvider(lambda s, p, sc: answer), CONFIG, robots_ok=lambda u: True,
                        http=StubHttp({"https://skylar.com": perfume})).run()
    assert hs.all("companies") == []                       # wrong domain never saved
    assert report.outcomes[0].note == "rejected skylar.com (a different company); brief from job posting only"
    deal = hs.objects["deals"][deal_id]["properties"]
    assert hs.stage_label(deal["dealstage"]) == "Researched" and "job posting only" in deal["job_analysis"]
