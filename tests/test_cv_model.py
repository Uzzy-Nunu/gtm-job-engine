"""Master CV parsing, assembling a tailored CV from AI picks, and rendering.
Made-up CV only (tests/fixtures/sample_cv_full.md)."""

import copy
from pathlib import Path

import pytest

from src.cv_model import (MAX_LINES, assemble, estimate_lines, fit_two_pages,
                          for_ai, master_text_for, parse_master_cv)
from src.render_docx import docx_to_text, render_cover_letter, render_cv
from tests.test_cv_template import _assert_ats_safe_structure

ROOT = Path(__file__).resolve().parents[1]
MASTER = parse_master_cv((ROOT / "tests" / "fixtures" / "sample_cv_full.md").read_text(encoding="utf-8"))

PICKS = {
    "headline": "GTM Engineer | Go-to-Market Systems | CRM",
    "summary": "Go-to-Market (GTM) engineer who builds outbound and CRM systems for small B2B teams.",
    "core_skills": ["B2B lead generation", "multichannel outreach", "workflow automation", "prompt engineering"],
    "tools": ["HubSpot", "Clay", "Make", "ChatGPT"],
    "roles": [
        {"role_id": "r4a", "title": "Sales Specialist",
         "bullets": [{"source_id": "r4ab1", "text": "Promoted to sales on KPI performance."}]},
        {"role_id": "r1", "title": "GTM Engineer (Freelance)",
         "bullets": [{"source_id": "r1b1", "text": "Design GTM and growth systems for founders and B2B teams, "
                                                   "including ICP definition and multichannel outreach."},
                     {"source_id": "r1b3", "text": "Rewrote outreach messaging that generated 3 replies from "
                                                   "the first 20 messages within two days."}]},
    ],
    "projects": [{"project_id": "p1", "bullets": [{"source_id": "p1b1", "text": "Building a system that scores "
                                                   "remote roles with AI and drafts applications for human review."}]}],
    "certification_ids": ["c1", "c2"],
}


# --- parsing -------------------------------------------------------------------------

def test_roles_employers_dates_and_progression():
    ids = [(r.id, r.title, r.company, r.dates) for r in MASTER.roles]
    assert ids == [
        ("r1", "Founder, Growth Consultant", "Sample Studio (Freelance)", "2023 - Present"),
        ("r2", "Marketing Assistant (Contract)", "Demo Co (via Upwork)", "Sep 2025 - Present"),
        ("r3", "Content Coach", "Self-employed", "2024 - Jan 2026"),
        ("r4a", "Sales Specialist", "Example Telecom", "2023 - 2024"),
        ("r4b", "Support Specialist", "Example Telecom", "2021 - 2023"),
        ("r5", "Brand Manager", "Placeholder Agency", "2019 - 2021"),
    ]
    assert MASTER.role("r1").variants == ["Growth Consultant (Freelance)", "GTM Engineer (Freelance)"]
    assert MASTER.role("r3").optional and MASTER.role("r5").optional.startswith("agency")
    assert [b.usable for b in MASTER.role("r1").bullets] == [True, True, True, False]   # [CONFIRM]


def test_other_sections():
    assert MASTER.contact["email"] == "alex.sample@example.com"
    assert "GTM Engineer" in MASTER.target_titles and "Founder's Associate" in MASTER.target_titles
    assert set(MASTER.summaries) == {"GTM-ENGINEER", "OPS-AUTOMATION"}
    assert "LLM integration (ChatGPT, Claude, Gemini)" in MASTER.all_skills()
    assert "Gemini API" in MASTER.all_tools() and "Python" not in MASTER.all_tools()   # "add after build" note ignored
    assert [p.name for p in MASTER.projects] == ["Job Search Engine (in progress)", "Booking Website"]
    assert MASTER.certifications[3].text == "TEFL Certificate | Example Record | 2024"
    assert MASTER.certifications[3].optional == "teaching"
    assert MASTER.education[1] == "University of Example, Countryland | 2013 - 2017"


def test_ai_view_has_ids_but_no_contact_unconfirmed_bullets_or_links():
    view = for_ai(MASTER)
    assert "[r1b1]" in view and "[r4bb1]" in view and "[p1b1]" in view and "[c4]" in view
    for private in ("alex.sample@example.com", "linkedin.com/in", "alex-sample.example.app",
                    "github.com", "Doubled a client", "booking.example.app"):
        assert private not in view
    assert "[OPTIONAL: agency, brand or content roles only]" in view


# --- assembling --------------------------------------------------------------------------

def test_valid_picks_become_a_cv_with_master_facts():
    result = assemble(MASTER, PICKS)
    cv = result.cv
    assert result.problems == []
    assert [(r["title"], r["company"], r["dates"]) for r in cv["experience"]] == [
        ("GTM Engineer (Freelance)", "Sample Studio (Freelance)", "2023 - Present"),   # master order restored
        ("Sales Specialist", "Example Telecom", "2023 - 2024"),
    ]
    assert cv["contact"] == {"email": "alex.sample@example.com", "linkedin": "linkedin.com/in/alex-sample-example",
                             "portfolio": "alex-sample.example.app"}
    assert cv["education"] == MASTER.education and cv["languages"] == ["English (Native) | French (Basic, A1)"]
    assert set(result.used_bullets) == {"r1b1", "r1b3", "r4ab1", "p1b1"}
    assert master_text_for(MASTER, ["r1b3"])["r1b3"].startswith("Rewritten outreach messaging")


@pytest.mark.parametrize("change,problem,invented", [
    (lambda p: p["roles"][1]["bullets"].append({"source_id": "r1b4", "text": "Doubled booked calls."}),
     "[CONFIRM]", "Doubled booked calls"),
    (lambda p: p["roles"][1]["bullets"].append({"source_id": "r9b9", "text": "Invented result."}),
     "unknown source", "Invented result"),
    (lambda p: p["roles"].append({"role_id": "r99", "title": "Chief Executive", "bullets": []}),
     "unknown role", "Chief Executive"),
    (lambda p: p["roles"][1].update(title="Head of Growth"), "isn't your real title", "Head of Growth"),
    (lambda p: p["core_skills"].append("Salesforce administration"), "skill not in your master CV", "Salesforce"),
    (lambda p: p["tools"].append("SQL"), "tool not in your master CV", "SQL"),
    (lambda p: p.update(headline="Chief Revenue Officer"), "isn't one of your target titles", "Chief Revenue"),
    (lambda p: p["certification_ids"].append("c99"), "unknown certification", "c99"),
])
def test_untraceable_picks_are_dropped_and_reported(change, problem, invented):
    picks = copy.deepcopy(PICKS)
    change(picks)
    result = assemble(MASTER, picks)
    assert any(problem in p for p in result.problems), result.problems
    assert invented not in str(result.cv)


def test_close_wording_maps_to_the_master_item():
    picks = copy.deepcopy(PICKS)
    picks["tools"] = ["Make.com", "Gemini"]           # "Gemini" is a whole word inside "Gemini API"
    picks["core_skills"] = ["LLM integration"]         # shorter than the master item
    cv = assemble(MASTER, picks).cv
    assert cv["tools"] == ["Make", "Gemini"] and cv["core_skills"] == ["LLM integration"]


# --- rendering and two pages ---------------------------------------------------------------

def test_tailored_cv_renders_ats_safe_with_master_dates(tmp_path):
    out = render_cv(assemble(MASTER, PICKS).cv, tmp_path / "cv.docx")
    _assert_ats_safe_structure(out)
    text = docx_to_text(out)
    assert text.splitlines()[:3] == [
        "Alex Sample", "GTM Engineer | Go-to-Market Systems | CRM",
        "Remote | alex.sample@example.com | linkedin.com/in/alex-sample-example | alex-sample.example.app"]
    assert "GTM Engineer (Freelance) - Sample Studio (Freelance)\n2023 - Present" in text
    assert "Bachelor of Arts (BA), Philosophy" in text
    assert all(c.isascii() for c in text)


def test_cover_letter_renders_plain_and_ats_safe(tmp_path):
    out = render_cover_letter({"name": "Alex Sample", "contact": {"email": "alex.sample@example.com"},
                               "date": "18 Nov 2026", "greeting": "Dear Hiring Team,",
                               "paragraphs": ["First “paragraph” — with smart quotes.", "Second."],
                               "closing": "Kind regards,"}, tmp_path / "cl.docx")
    _assert_ats_safe_structure(out)
    text = docx_to_text(out)
    assert text.startswith("Alex Sample\nRemote | alex.sample@example.com\n18 Nov 2026\nDear Hiring Team,")
    assert '"paragraph" - with smart quotes.' in text and text.endswith("Kind regards,\nAlex Sample")


def test_long_cvs_are_trimmed_to_two_pages_oldest_first():
    cv = assemble(MASTER, PICKS).cv
    long_bullet = "Built and ran a long, detailed programme of work " * 4
    for role in cv["experience"]:
        role["bullets"] = [long_bullet] * 5
    cv["experience"] = [copy.deepcopy(r) for r in cv["experience"] * 4]
    problems = []
    fitted = fit_two_pages(cv, problems)
    assert estimate_lines(fitted) <= MAX_LINES
    assert problems and problems[0].startswith("Trimmed")
    assert all(len(r["bullets"]) >= 1 for r in fitted["experience"])
    assert len(fitted["experience"][0]["bullets"]) >= len(fitted["experience"][-1]["bullets"])
