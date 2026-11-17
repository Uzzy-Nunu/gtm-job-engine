"""Tests for the AI provider layer and the master CV reader (no network)."""

import json
from pathlib import Path

import pytest

from src.llm import (ClaudeProvider, FakeProvider, GeminiProvider, LLMError,
                     _parse_json, make_llm)
from src.cv_sections import MasterCVError, load_text, qualify_profile, sections

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CV = (ROOT / "tests" / "fixtures" / "sample_cv_profile.md").read_text(encoding="utf-8")
SCHEMA = {"type": "object", "required": ["ok", "score"], "additionalProperties": False,
          "properties": {"ok": {"type": "boolean"}, "score": {"type": "integer", "minimum": 0, "maximum": 100}}}


class Resp:
    def __init__(self, status, body=None, headers=None, text=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(self._body)

    def json(self):
        return self._body


class Session:
    """Replays canned responses and records request bodies."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        self.bodies.append((url, json))
        return self.responses.pop(0)


def gemini_ok(payload):
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})


def gemini(session, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("min_interval", 0)
    return GeminiProvider("test-key", {"fast": "gemini-test-lite", "draft": "gemini-test"}, session=session, **kw)


# --- Gemini --------------------------------------------------------------

def test_gemini_request_shape_and_answer():
    s = Session([gemini_ok({"ok": True, "score": 80})])
    out = gemini(s).generate_json(system="Be strict.", prompt="Score this.", schema=SCHEMA)
    assert out == {"ok": True, "score": 80}
    url, body = s.bodies[0]
    assert url.endswith("/models/gemini-test-lite:generateContent")
    assert body["systemInstruction"]["parts"][0]["text"] == "Be strict."
    assert body["contents"][0]["parts"][0]["text"] == "Score this."
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"] == SCHEMA
    assert s.headers["x-goog-api-key"] == "test-key"


def test_draft_role_uses_the_draft_model():
    s = Session([gemini_ok({"ok": True, "score": 1})])
    gemini(s).generate_json(system="", prompt="x", schema=SCHEMA, role="draft")
    assert s.bodies[0][0].endswith("/models/gemini-test:generateContent")


def test_invalid_answer_is_retried_once_then_fails_loudly():
    s = Session([gemini_ok({"ok": "yes"}), gemini_ok({"ok": True, "score": 5})])
    assert gemini(s).generate_json(system="", prompt="x", schema=SCHEMA)["score"] == 5
    assert "previous answer was invalid" in s.bodies[1][1]["contents"][0]["parts"][0]["text"]

    s = Session([gemini_ok({"score": 500}), gemini_ok({"ok": True, "score": 500})])
    with pytest.raises(LLMError, match="invalid output twice"):
        gemini(s).generate_json(system="", prompt="x", schema=SCHEMA)


def test_rate_limit_is_retried_with_the_suggested_delay():
    slept = []
    busy = Resp(429, {"error": {"details": [{"@type": "RetryInfo", "retryDelay": "7s"}]}})
    s = Session([busy, gemini_ok({"ok": True, "score": 3})])
    out = gemini(s, sleep=slept.append).generate_json(system="", prompt="x", schema=SCHEMA)
    assert out["score"] == 3 and 7.0 in slept


def test_gives_up_after_max_retries():
    s = Session([Resp(503), Resp(503)])
    with pytest.raises(LLMError, match="busy"):
        gemini(s, max_retries=1).generate_json(system="", prompt="x", schema=SCHEMA)


def test_falls_back_to_plain_json_mode_if_schema_field_is_rejected():
    s = Session([Resp(400, text='Invalid JSON payload. Unknown name "responseJsonSchema"'),
                 gemini_ok({"ok": True, "score": 9})])
    assert gemini(s).generate_json(system="", prompt="x", schema=SCHEMA)["score"] == 9
    assert "responseJsonSchema" not in s.bodies[1][1]["generationConfig"]


def test_blocked_or_empty_answers_are_errors():
    with pytest.raises(LLMError, match="SAFETY"):
        gemini(Session([Resp(200, {"promptFeedback": {"blockReason": "SAFETY"}})])).generate_json(
            system="", prompt="x", schema=SCHEMA)


def test_missing_key_is_a_clear_error():
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        GeminiProvider("", {"fast": "m"})


def test_requests_are_spaced_out():
    slept = []
    clock = iter([0.0, 1.0, 1.0])  # 1st call at t=0; 2nd asks at t=1, so waits 3 more seconds
    s = Session([gemini_ok({"ok": True, "score": 1}), gemini_ok({"ok": True, "score": 2})])
    p = gemini(s, sleep=slept.append, clock=lambda: next(clock), min_interval=4)
    p.generate_json(system="", prompt="a", schema=SCHEMA)
    p.generate_json(system="", prompt="b", schema=SCHEMA)
    assert slept == [3.0]


# --- Claude and the factory ------------------------------------------------

def test_claude_request_shape():
    s = Session([Resp(200, {"content": [{"type": "text", "text": '{"ok": true, "score": 42}'}]})])
    p = ClaudeProvider("k", {"fast": "claude-haiku-5-5"}, session=s, sleep=lambda x: None, min_interval=0)
    assert p.generate_json(system="Sys", prompt="P", schema=SCHEMA)["score"] == 42
    url, body = s.bodies[0]
    assert body["model"] == "claude-haiku-5-5" and body["messages"][0]["content"] == "P"
    assert "JSON Schema" in body["system"] and s.headers["anthropic-version"] == "2023-06-01"


def test_make_llm_reads_config():
    p = make_llm({"llm": {"provider": "gemini", "fast_model": "a", "draft_model": "b"}}, api_key="k")
    assert isinstance(p, GeminiProvider) and p.models == {"fast": "a", "draft": "b"}
    with pytest.raises(LLMError, match="Unknown"):
        make_llm({"llm": {"provider": "other"}}, api_key="k")


def test_fake_provider_and_fenced_json():
    fake = FakeProvider(lambda system, prompt, schema: '```json\n{"ok": false, "score": 0}\n```')
    assert fake.generate_json(system="", prompt="hi", schema=SCHEMA) == {"ok": False, "score": 0}
    assert fake.prompts == ["hi"]
    assert _parse_json('{"a": 1}') == {"a": 1}


# --- master CV ---------------------------------------------------------------

def test_qualify_profile_has_skills_but_never_contact_details():
    profile = qualify_profile(SAMPLE_CV)
    for wanted in ("TARGET TITLES", "CORE SKILLS", "TOOLS & TECHNOLOGIES", "HubSpot", "Make"):
        assert wanted in profile
    for private in ("alex.sample@example.com", "linkedin.com/in/alex-sample-example",
                    "555-0199", "CONTACT", "Example Analytics", "PROFESSIONAL EXPERIENCE"):
        assert private not in profile


def test_sections_are_split_by_heading():
    names = list(sections(SAMPLE_CV))
    assert names[1].startswith("CONTACT") and "TOOLS & TECHNOLOGIES" in names


def test_master_cv_comes_from_secret_or_local_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MASTER_CV", SAMPLE_CV)
    assert "Alex Sample" in load_text()
    monkeypatch.setenv("MASTER_CV", "")
    f = tmp_path / "cv.md"
    f.write_text("## CORE SKILLS\nx", encoding="utf-8")
    monkeypatch.setenv("MASTER_CV_PATH", str(f))
    assert load_text().startswith("## CORE SKILLS")
    monkeypatch.setenv("MASTER_CV_PATH", "")
    with pytest.raises(MasterCVError, match="MASTER_CV"):
        load_text()
