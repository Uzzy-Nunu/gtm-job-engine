"""Tests for the generic RSS/Atom reader (src/sources/feeds.py). Made-up feeds only."""

from datetime import datetime, timezone

import pytest

from src.fake_hubspot import FakeHubSpot
from src.importer import run_import
from src.sources.feeds import read_feed, split_title

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:job="https://jobs.example/ns">
<channel><title>Sample niche board</title>
<item>
  <title>GTM Engineer at Fictional Labs</title>
  <link>https://niche.example/jobs/1?utm_source=rss</link>
  <description>&lt;p&gt;Build outbound systems.&lt;/p&gt;</description>
  <job:location>Remote (Worldwide)</job:location>
  <pubDate>Mon, 16 Nov 2026 10:00:00 +0000</pubDate>
</item>
<item>
  <title>Demo Co: Demand Generation Manager</title>
  <link>https://niche.example/jobs/2</link>
  <description>Run paid and lifecycle programmes.</description>
  <region>USA Only</region>
  <pubDate>Mon, 16 Nov 2026 10:00:00 +0000</pubDate>
</item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Sample company careers</title>
  <entry>
    <title>Marketing Automation Lead</title>
    <link rel="alternate" href="https://careers.samplecorp.example/jobs/7"/>
    <updated>2026-11-15T09:00:00Z</updated>
    <summary>HubSpot, Zapier, lifecycle.</summary>
  </entry>
</feed>"""


class StubHttp:
    def __init__(self, pages):
        self.pages = pages

    def text(self, url, params=None):
        return self.pages[url]


@pytest.mark.parametrize("title,fmt,expected", [
    ("GTM Engineer at Fictional Labs", "auto", ("GTM Engineer", "Fictional Labs")),
    ("Demo Co: Growth Lead", "auto", ("Growth Lead", "Demo Co")),
    ("Growth Lead at Demo Co (Remote)", "auto", ("Growth Lead", "Demo Co")),
    ("Head of RevOps", "auto", ("Head of RevOps", "")),
    ("Demo Co: Growth Lead", "role", ("Demo Co: Growth Lead", "")),
])
def test_split_title(title, fmt, expected):
    assert split_title(title, fmt) == expected


def test_reads_rss_with_namespaced_location():
    jobs = read_feed(StubHttp({"https://niche.example/rss": RSS}),
                     {"name": "Niche Board", "url": "https://niche.example/rss"})
    assert [(j.title, j.company, j.location) for j in jobs] == [
        ("GTM Engineer", "Fictional Labs", "Remote (Worldwide)"),
        ("Demand Generation Manager", "Demo Co", "USA Only"),
    ]
    assert jobs[0].source == "Other"
    assert jobs[0].text.startswith("Board: Niche Board")
    assert "Build outbound systems." in jobs[0].text
    assert jobs[0].posted_at == datetime(2026, 11, 16, 10, tzinfo=timezone.utc)


def test_link_from_guid_gives_a_stable_job_link():
    rss = RSS.replace("<link>https://niche.example/jobs/1?utm_source=rss</link>",
                      "<link>https://niche.example/job/gtm-engineer/</link>"
                      "<guid isPermaLink=\"false\">https://niche.example/?post_type=job_listing&amp;p=101</guid>")
    jobs = read_feed(StubHttp({"https://niche.example/rss": rss}),
                     {"name": "Niche", "url": "https://niche.example/rss", "link_from": "guid"})
    assert jobs[0].url == "https://niche.example/?post_type=job_listing&p=101"


def test_reads_atom_and_company_override():
    jobs = read_feed(StubHttp({"https://careers.samplecorp.example/feed": ATOM}),
                     {"name": "SampleCorp careers", "url": "https://careers.samplecorp.example/feed",
                      "company": "SampleCorp"})
    assert len(jobs) == 1
    assert jobs[0].url == "https://careers.samplecorp.example/jobs/7"
    assert (jobs[0].title, jobs[0].company) == ("Marketing Automation Lead", "SampleCorp")


def test_extra_feeds_flow_through_the_import():
    config = {
        "target_titles": ["GTM Engineer", "Marketing Automation"],
        "adjacent_titles": ["Demand Generation"],
        "excluded_title_words": [],
        "eligible_regions": ["Worldwide"],
        "public_feeds": {},
        "companies": {},
        "daily_import_cap": 40,
        "timezone": "Africa/Lagos",
        "extra_feeds": [
            {"name": "Niche Board", "url": "https://niche.example/rss"},
            {"name": "SampleCorp careers", "url": "https://careers.samplecorp.example/feed",
             "company": "SampleCorp"},
            {"name": "Paused board", "url": "https://paused.example/rss", "enabled": False},
        ],
    }
    http = StubHttp({"https://niche.example/rss": RSS, "https://careers.samplecorp.example/feed": ATOM})
    hs = FakeHubSpot()
    report = run_import(config, hs, http, now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    assert report.ok, report.errors
    assert report.fetched == {"Niche Board": 2, "SampleCorp careers": 1}  # paused board not read
    names = sorted(d["properties"]["dealname"] for d in hs.all("deals"))
    assert names == ["GTM Engineer - Fictional Labs", "Marketing Automation Lead - SampleCorp"]
    assert report.skipped["location"] == 1  # the USA Only role
    assert {d["properties"]["job_source"] for d in hs.all("deals")} == {"Other"}


def test_broken_extra_feed_is_reported_by_name():
    config = {"target_titles": ["GTM Engineer"], "public_feeds": {}, "companies": {},
              "timezone": "UTC", "extra_feeds": [{"name": "Broken board", "url": "https://broken.example/rss"}]}
    report = run_import(config, FakeHubSpot(), StubHttp({}), now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    assert not report.ok
    assert report.errors[0].startswith("Broken board:")
