"""Draft step tests: made-up master CV, made-up AI answers, fake HubSpot."""

import copy
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from src.draft import (DRAFT_SCHEMA, NOTE_LIMIT, TRUTH_SCHEMA, Drafter, file_stem,
                       limit_followup, limit_note)
from src.fake_hubspot import FakeHubSpot
from src.llm import FakeProvider, LLMError
from src.render_docx import docx_to_text
from tests.test_cv_model import PICKS
from tests.test_cv_template import _assert_ats_safe_structure

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
MASTER_TEXT = (ROOT / "tests" / "fixtures" / "sample_cv_full.md").read_text(encoding="utf-8")

LETTER = ["SampleCorp is building the outbound engine its revenue team needs, and that is the work I do. " * 3,
          "At Sample Studio I design go-to-market systems for founders, covering ICP definition and outreach. " * 3,
          "I'd welcome a conversation about the role. " * 3]
DRAFT = dict(copy.deepcopy(PICKS), **{
    "cover_letter": {"greeting": "Dear SampleCorp team,", "paragraphs": LETTER, "closing": "Kind regards,"},
    "connection_note": "Hi, I saw SampleCorp is hiring a GTM Engineer. I build outbound and CRM systems with Clay and HubSpot and would love to connect.",
    "followup_message": "Thanks for considering my application for the GTM Engineer role. I build outbound systems.",
    "keyword_coverage": [
        {"requirement": "Outbound automation", "covered": True, "evidence": "r1b1"},
        {"requirement": "HubSpot", "covered": True, "evidence": "tools"},
        {"requirement": "Clay", "covered": True, "evidence": "tools"},
        {"requirement": "SQL", "covered": False, "evidence": None},
    ],
})
NO_ISSUES = {"issues": []}


def fake_ai(draft=None, truth=None):
    def answer(system, prompt, schema):
        if "fact-checker" in system:
            return truth if truth is not None else NO_ISSUES
        return draft if draft is not None else DRAFT
    return FakeProvider(answer)


def seed(hs, name="GTM Engineer - SampleCorp", stage="Researched", **props):
    stage_id = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == stage)
    return hs.post("/crm/v3/objects/deals", {"properties": {
        "dealname": name, "pipeline": "default", "dealstage": stage_id, "fit_score": props.pop("fit_score", "90"),
        "job_url": f"https://jobs.example/{name}",
        "description": "We need a GTM Engineer for outbound automation with Clay and HubSpot. "
                       "Questions: hiring@samplecorp.example\n\n--- Notes from Peace ---\nprivate note",
        "job_analysis": "Fit score: 90/100\n\nCompany brief:\n- SampleCorp sells analytics.", **props}})["id"]


def drafter(hs, llm=None, tmp_path=Path("output/test-drafts"), **kw):
    return Drafter(hs, llm or fake_ai(), CONFIG, MASTER_TEXT, tmp_path, today=date(2026, 11, 18), **kw)


def test_draft_produces_cv_letter_messages_and_coverage(tmp_path):
    hs = FakeHubSpot()
    seed(hs)
    report = drafter(hs, tmp_path=tmp_path).run()
    assert report.ok and len(report.drafts) == 1
    d = report.drafts[0]
    assert d.cv_path.name == "Alex-Sample-CV-SampleCorp.docx"
    assert d.letter_path.name == "Alex-Sample-Cover-Letter-SampleCorp.docx"
    for path in (d.cv_path, d.letter_path):
        _assert_ats_safe_structure(path)
    cv_text = docx_to_text(d.cv_path)
    assert "Remote | alex.sample@example.com" in cv_text
    assert "GTM Engineer (Freelance) - Sample Studio (Freelance)\n2023 - Present" in cv_text
    letter_text = docx_to_text(d.letter_path)
    assert letter_text.startswith("Alex Sample\nRemote | ") and letter_text.endswith("Kind regards,\nAlex Sample")
    assert d.coverage_pct == 75 and d.missing == ["SQL"]
    assert d.truth_checked and d.truth_issues == []


def test_ai_never_sees_contact_details_notes_or_unconfirmed_bullets(tmp_path):
    hs = FakeHubSpot()
    seed(hs)
    llm = fake_ai()
    drafter(hs, llm, tmp_path=tmp_path).run()
    draft_prompt, truth_prompt = llm.prompts
    for prompt in (draft_prompt, truth_prompt):
        for private in ("alex.sample@example.com", "linkedin.com/in/alex", "hiring@samplecorp.example",
                        "private note", "Doubled a client"):
            assert private not in prompt
    assert "[r1b1]" in draft_prompt and "SampleCorp sells analytics" in draft_prompt
    assert "SOURCE: Rewritten outreach messaging" in truth_prompt    # originals given to the checker


def test_invented_picks_never_reach_the_cv(tmp_path):
    bad = copy.deepcopy(DRAFT)
    bad["roles"][1]["bullets"].append({"source_id": "r1b4", "text": "Doubled booked calls for every client."})
    bad["tools"].append("Salesforce")
    hs = FakeHubSpot()
    seed(hs)
    d = drafter(hs, fake_ai(draft=bad), tmp_path=tmp_path).run().drafts[0]
    text = docx_to_text(d.cv_path)
    assert "Doubled booked calls" not in text and "Salesforce" not in text
    assert any("[CONFIRM]" in p for p in d.problems) and any("Salesforce" in p for p in d.problems)


def test_message_and_letter_limits(tmp_path):
    long = copy.deepcopy(DRAFT)
    long["connection_note"] = "I build outbound systems. " * 30
    long["followup_message"] = "word " * 150
    long["cover_letter"]["paragraphs"] = ["Too short.", "Still short."]
    hs = FakeHubSpot()
    seed(hs)
    d = drafter(hs, fake_ai(draft=long), tmp_path=tmp_path).run().drafts[0]
    assert len(d.connection_note) <= NOTE_LIMIT and d.connection_note.endswith(".")
    assert len(d.followup.split()) <= 120
    assert any("Cover letter is 4 words" in p for p in d.problems)
    assert any("Connection note shortened" in p for p in d.problems)


def test_truth_issues_are_recorded(tmp_path):
    issues = {"issues": [{"where": "r1b3", "claim": "generated 30 replies", "problem": "source says 3 replies"}]}
    hs = FakeHubSpot()
    seed(hs)
    report = drafter(hs, fake_ai(truth=issues), tmp_path=tmp_path).run()
    assert report.drafts[0].truth_issues == issues["issues"]
    assert "truth check: 1 issue(s)" in "\n".join(report.lines())


def test_truth_check_failure_is_flagged_not_hidden(tmp_path):
    def answer(system, prompt, schema):
        if "fact-checker" in system:
            raise LLMError("Gemini 400: bad request")
        return DRAFT
    hs = FakeHubSpot()
    seed(hs)
    d = drafter(hs, FakeProvider(answer), tmp_path=tmp_path).run().drafts[0]
    assert not d.truth_checked and any("review every claim by hand" in p for p in d.problems)


def test_daily_cap_counts_todays_ready_for_review(tmp_path):
    hs = FakeHubSpot()
    seed(hs, name="Already done - X", stage="Ready for Review")
    seed(hs, name="GTM Engineer - A", fit_score="95")
    seed(hs, name="GTM Engineer - B", fit_score="80")
    config = dict(CONFIG, daily_draft_cap=2)
    report = Drafter(hs, fake_ai(), config, MASTER_TEXT, tmp_path, today=date(2026, 11, 18)).run()
    assert report.room == 1 and [d.deal_name for d in report.drafts] == ["GTM Engineer - A"]
    assert report.waiting == 1


def test_log_lines_hold_no_cv_or_letter_text(tmp_path):
    hs = FakeHubSpot()
    seed(hs)
    lines = "\n".join(drafter(hs, tmp_path=tmp_path).run().lines())
    for private in ("Sample Studio", "ICP definition", "Dear SampleCorp", "Clay and HubSpot", "alex.sample"):
        assert private not in lines
    assert "coverage 75%" in lines and "truth check: passed" in lines


def test_skips_errors_and_stops_when_busy(tmp_path):
    hs = FakeHubSpot()
    seed(hs, name="Flagged - X", pipeline_error="TRUTH CHECK: earlier")
    seed(hs, name="GTM Engineer - Y")

    def busy(system, prompt, schema):
        raise LLMError("Gemini 429", retryable=True)

    report = drafter(hs, FakeProvider(busy, max_retries=0), tmp_path=tmp_path).run()
    assert report.skipped[0][2] == "TRUTH CHECK" and report.stopped and report.waiting == 1


def test_helpers_and_schemas():
    assert file_stem("Peace George", "Cover Letter", "Skylar Inc.") == "Peace-George-Cover-Letter-Skylar-Inc"
    problems = []
    assert limit_note("Short note.", problems) == "Short note." and problems == []
    assert limit_followup("a " * 10, problems).strip() == ("a " * 10).strip()
    assert "keyword_coverage" in DRAFT_SCHEMA["required"] and "issues" in TRUTH_SCHEMA["required"]
    assert "poster" not in str(DRAFT_SCHEMA)
