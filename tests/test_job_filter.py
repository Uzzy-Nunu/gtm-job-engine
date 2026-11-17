"""Tests for src/job_filter.py."""

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from src.job_filter import TitleFilter, is_recent, looks_remote, region_ok

from pathlib import Path

CONFIG = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8"))
TITLES = TitleFilter.from_config(CONFIG)
ELIGIBLE = CONFIG["eligible_regions"]


@pytest.mark.parametrize("title,expected", [
    ("Senior GTM Engineer", "target"),
    ("Go-to-Market Engineer (Remote)", "target"),
    ("RevOps Lead", "target"),
    ("Head of Revenue Operations", "target"),
    ("Marketing Automation Specialist", "target"),
    ("Growth Marketing Manager", "adjacent"),
    ("Founder's Associate - Growth", "adjacent"),
    ("AI Operations Lead", "target"),
    ("AI Automation Specialist", "target"),
    ("Senior AI Implementation Consultant", "target"),
    ("AI Solutions Consultant", "target"),
    ("AI Workflow Engineer", "target"),
    ("Workflow Automation Specialist (Make, n8n)", "target"),
    ("Chief of Staff to the CEO", "adjacent"),
    ("GTM Strategist", "adjacent"),
    ("HubSpot Administrator", "explore"),
    ("Applied AI Specialist", "explore"),
    ("Customer Success Manager (SaaS)", "explore"),
    ("Customer Success Operations Specialist", "explore"),
    ("CX Operations Lead", "explore"),
    ("QA Automation Engineer", None),
    ("Test Automation Specialist", None),
    ("Machine Learning Engineer, Applied AI", None),
    ("Growth Manager", "adjacent"),
    ("Growth Lead, EMEA", "adjacent"),
    ("Product Growth Manager (Acquisition Funnels)", "adjacent"),
    ("Sr. Marketing Technology Strategist", "adjacent"),
    ("MarTech Strategist", "adjacent"),
    ("Lead Generation Specialist", "adjacent"),
    ("Demand Generation Manager", "adjacent"),
    ("Senior Growth Product Manager", None),   # product role, not growth
    ("Account Executive, Growth", None),       # excluded word wins
    ("SDR Team Lead - Revenue Operations", None),
    ("Senior Software Engineer, Growth", None),
    ("Engineering Manager", None),
    ("Marketing Engineering Intern", None),
])
def test_title_filter(title, expected):
    assert TITLES.match(title) == expected


@pytest.mark.parametrize("location,workplace,expected", [
    ("Remote", "", True),
    ("", "", True),                    # unknown: let Qualify decide
    ("London Office", "", False),
    ("Berlin", "hybrid", False),
    ("Berlin", "remote", True),
    ("Anywhere", "", True),
])
def test_looks_remote(location, workplace, expected):
    assert looks_remote(location, workplace) is expected


@pytest.mark.parametrize("location,expected", [
    ("Worldwide", True),
    ("Anywhere in the World", True),
    ("Remote", True),
    ("Fully remote", True),
    ("", True),
    ("Remote, EMEA", True),
    ("Africa", True),
    ("Remote - Nigeria", True),
    ("USA Only", False),
    ("Remote - US", False),
    ("United States, Canada", False),
    ("Europe", False),
    ("South Africa", False),             # a country, not the Africa region
    ("South Africa, Nigeria, Kenya", True),
    ("Remote - Africa", True),
])
def test_region_ok(location, expected):
    assert region_ok(location, ELIGIBLE) is expected


def test_is_recent():
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    assert is_recent(now - timedelta(days=3), 14, now)
    assert not is_recent(now - timedelta(days=30), 14, now)
    assert is_recent(None, 14, now)


def test_explore_titles_rank_after_core_lists():
    tf = TitleFilter(["GTM Engineer"], ["Growth Marketing"], ["Intern"],
                     explore=["Lifecycle Marketing", "Growth"])
    assert tf.match("Lifecycle Marketing Manager") == "explore"
    assert tf.match("Growth Marketing Lead") == "adjacent"      # core list wins
    assert tf.match("GTM Engineer, Growth") == "target"
    assert tf.match("Lifecycle Marketing Intern") is None        # excluded still wins
    assert TitleFilter(["GTM Engineer"], [], []).match("Lifecycle Marketing Manager") is None
