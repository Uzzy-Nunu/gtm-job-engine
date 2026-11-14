"""Tests for src/urls.py, driven by the shared fixture used by the Worker too."""

import json
from pathlib import Path

import pytest

from src.urls import (URLError, company_domain, find_external_job_links,
                      normalise_url, parse_linkedin_post)

CASES = json.loads((Path(__file__).parent / "fixtures" / "linkedin_urls.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["valid"], ids=lambda c: c["post_id"])
def test_parse_valid_linkedin_posts(case):
    post = parse_linkedin_post(case["url"])
    for key in ("post_id", "urn_type", "canonical_url", "author_slug", "profile_url", "name_guess"):
        assert getattr(post, key) == case[key], key


@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda c: c["url"].strip() or "blank")
def test_invalid_links_give_helpful_errors(case):
    with pytest.raises(URLError, match=case["error_contains"]):
        parse_linkedin_post(case["url"])


@pytest.mark.parametrize("raw,expected", CASES["normalise"])
def test_normalise_url(raw, expected):
    assert normalise_url(raw) == expected


def test_linkedin_links_normalise_to_the_canonical_post():
    a = normalise_url(CASES["valid"][0]["url"])
    b = normalise_url("https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001")
    assert a == b  # same post, different link styles -> one duplicate key


def test_find_external_job_links_skips_linkedin():
    text = ("We're hiring! Apply: https://boards.greenhouse.io/samplecorp/jobs/123?gh_src=li. "
            "More at https://www.linkedin.com/company/samplecorp and "
            "https://samplecorp.example/careers/gtm.")
    assert find_external_job_links(text) == [
        "https://boards.greenhouse.io/samplecorp/jobs/123",
        "https://samplecorp.example/careers/gtm",
    ]


def test_company_domain():
    assert company_domain("https://careers.samplecorp.example/jobs/1") == "samplecorp.example"
    assert company_domain("https://boards.greenhouse.io/samplecorp/jobs/1") is None
    assert company_domain("https://www.demo.example/jobs") == "demo.example"
