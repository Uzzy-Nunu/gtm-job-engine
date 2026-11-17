"""Draft step (PRD §10.4): tailored CV, cover letter, messages, keyword
coverage and a truth check for each Researched deal.

Per deal (highest Fit Score first, up to the daily draft cap):
  1. The drafting AI (draft model) picks and rewords numbered CV pieces and
     writes the cover letter, connection note, follow-up and keyword coverage
     (prompts/draft.md). It never sees contact details.
  2. Code assembles the CV from the master CV's own employers, dates and titles
     and drops anything untraceable (src/cv_model.py), fits it to two pages, and
     enforces message limits.
  3. The truth-check AI compares every reworded bullet with its source and the
     letter and messages with the CV (prompts/truth_check.md).
  4. The CV and cover letter are rendered as .docx files.

Logs show counts and scores only: CV text, letters and messages never appear in
logs (GitHub Actions logs on a public repo are public).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.cv_model import MasterCV, assemble, fit_two_pages, for_ai, master_text_for, parse_master_cv
from src.hubspot_client import HubSpotError
from src.hubspot_schema import PIPELINE_LABEL
from src.llm import LLMError
from src.qualify import load_prompt, public_name
from src.redact import redact, strip_notes
from src.render_docx import render_cover_letter, render_cv

ROOT = Path(__file__).resolve().parents[1]
DRAFT_PROMPT = ROOT / "prompts" / "draft.md"
TRUTH_PROMPT = ROOT / "prompts" / "truth_check.md"
MAX_JOB = 8_000
MAX_ANALYSIS = 6_000
NOTE_LIMIT = 300        # characters (DR-4)
FOLLOWUP_LIMIT = 120    # words (DR-5)
LETTER_WORDS = (200, 300)
FILES_FOLDER = "/gtm-job-engine/drafts"
DRAFTS_MARKER = "\n\nDrafts ("
NOTE_TO_DEAL = 214      # HubSpot-defined association type: note -> deal

_BULLETS = {"type": "array", "items": {
    "type": "object", "required": ["source_id", "text"],
    "properties": {"source_id": {"type": "string"}, "text": {"type": "string"}}}}

DRAFT_SCHEMA = {
    "type": "object",
    "required": ["headline", "summary", "core_skills", "tools", "roles", "projects", "certification_ids",
                 "cover_letter", "connection_note", "followup_message", "keyword_coverage"],
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "core_skills": {"type": "array", "items": {"type": "string"}},
        "tools": {"type": "array", "items": {"type": "string"}},
        "roles": {"type": "array", "items": {
            "type": "object", "required": ["role_id", "title", "bullets"],
            "properties": {"role_id": {"type": "string"}, "title": {"type": "string"}, "bullets": _BULLETS}}},
        "projects": {"type": "array", "items": {
            "type": "object", "required": ["project_id", "bullets"],
            "properties": {"project_id": {"type": "string"}, "bullets": _BULLETS}}},
        "certification_ids": {"type": "array", "items": {"type": "string"}},
        "cover_letter": {"type": "object", "required": ["greeting", "paragraphs", "closing"], "properties": {
            "greeting": {"type": "string"},
            "paragraphs": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
            "closing": {"type": "string"}}},
        "connection_note": {"type": "string"},
        "followup_message": {"type": "string"},
        "keyword_coverage": {"type": "array", "items": {
            "type": "object", "required": ["requirement", "covered"],
            "properties": {"requirement": {"type": "string"}, "covered": {"type": "boolean"},
                           "evidence": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}},
    },
}

TRUTH_SCHEMA = {
    "type": "object", "required": ["issues"],
    "properties": {"issues": {"type": "array", "items": {
        "type": "object", "required": ["where", "claim", "problem"],
        "properties": {"where": {"type": "string"}, "claim": {"type": "string"}, "problem": {"type": "string"}}}}},
}


@dataclass
class Draft:
    deal_id: str
    deal_name: str
    company: str
    cv: dict
    letter: dict
    connection_note: str
    followup: str
    coverage_pct: int
    covered: list[str]
    missing: list[str]
    problems: list[str] = field(default_factory=list)
    truth_issues: list[dict] = field(default_factory=list)
    truth_checked: bool = True
    cv_path: Path | None = None
    letter_path: Path | None = None


@dataclass
class DraftReport:
    drafts: list[Draft] = field(default_factory=list)
    skipped: list[tuple[str, str, str]] = field(default_factory=list)   # (deal id, name, reason)
    errors: list[tuple[str, str, str]] = field(default_factory=list)
    waiting: int = 0
    room: int = 0
    stopped: str | None = None
    ai_calls: int = 0
    busy_retries: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors and not self.stopped

    def lines(self) -> list[str]:
        """Counts and scores only: no CV text, letters or messages (public logs)."""
        flagged = sum(1 for d in self.drafts if d.truth_issues or not d.truth_checked)
        out = [f"Drafted: {len(self.drafts)} | truth-check flags: {flagged} | skipped: {len(self.skipped)} | "
               f"errors: {len(self.errors)} | AI requests: {self.ai_calls} (busy retries: {self.busy_retries}) | "
               f"room today: {self.room} | left for later: {self.waiting}"]
        if self.stopped:
            out.append(f"! Stopped early: {self.stopped}")
        for d in self.drafts:
            truth = ("truth check: not run" if not d.truth_checked else
                     f"truth check: {len(d.truth_issues)} issue(s)" if d.truth_issues else "truth check: passed")
            bullets = sum(len(r["bullets"]) for r in d.cv.get("experience", []))
            out.append(f"  Drafted   {public_name(d.deal_name, d.deal_id)} | coverage {d.coverage_pct}% | "
                       f"{bullets} bullets | {truth} | notes: {len(d.problems)}")
        for deal_id, name, reason in self.skipped:
            out.append(f"  skipped   {public_name(name, deal_id)} ({reason})")
        for deal_id, name, reason in self.errors:
            out.append(f"  error     {public_name(name, deal_id)} ({reason})")
        return out


def file_stem(person: str, kind: str, company: str) -> str:
    """'Peace George', 'CV', 'Skylar Inc.' -> 'Peace-George-CV-Skylar-Inc' (PRD DR-10)."""
    def slug(text):
        return "-".join(re.findall(r"[A-Za-z0-9]+", text or "")) or "Company"
    return f"{slug(person)}-{slug(kind)}-{slug(company)}"


def limit_note(text: str, problems: list[str]) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= NOTE_LIMIT:
        return text
    cut = text[:NOTE_LIMIT]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    cut = cut[:end + 1] if end > 120 else cut[:cut.rfind(" ")].rstrip(",;:") + "."
    problems.append(f"Connection note shortened to {len(cut)} characters (limit {NOTE_LIMIT}).")
    return cut


def limit_followup(text: str, problems: list[str]) -> str:
    words = (text or "").split()
    if len(words) <= FOLLOWUP_LIMIT:
        return (text or "").strip()
    problems.append(f"Follow-up shortened from {len(words)} to {FOLLOWUP_LIMIT} words; check it reads well.")
    return " ".join(words[:FOLLOWUP_LIMIT]).rstrip(",;:") + "..."


class Drafter:
    def __init__(self, hubspot, llm, config: dict, master_text: str, out_dir: Path,
                 write: bool = False, today: date | None = None, now=None):
        self.hs = hubspot
        self.llm = llm
        self.config = config
        self.master: MasterCV = parse_master_cv(master_text)
        self.out_dir = Path(out_dir)
        self.write = write
        self.today = today or date.today()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.draft_system, self.draft_user = load_prompt(DRAFT_PROMPT)
        self.truth_system, self.truth_user = load_prompt(TRUTH_PROMPT)
        self.stage, self.pipeline_id = {}, None

    # --- HubSpot -------------------------------------------------------------
    def _resolve(self):
        for p in self.hs.get("/crm/v3/pipelines/deals").get("results", []):
            if p.get("label") == PIPELINE_LABEL:
                self.pipeline_id = p["id"]
                self.stage = {s["label"]: s["id"] for s in p.get("stages", [])}
        missing = [s for s in ("Researched", "Ready for Review") if s not in self.stage]
        if not self.pipeline_id or missing:
            raise HubSpotError(404, f"Pipeline '{PIPELINE_LABEL}' or stages {missing} not found.", "SETUP", "pipelines")

    def _search(self, stage: str, extra=None, limit=100):
        filters = [{"propertyName": "pipeline", "operator": "EQ", "value": self.pipeline_id},
                   {"propertyName": "dealstage", "operator": "EQ", "value": self.stage[stage]}] + (extra or [])
        return self.hs.post("/crm/v3/objects/deals/search", {
            "filterGroups": [{"filters": filters}],
            "properties": ["dealname", "description", "job_analysis", "pipeline_error", "fit_score", "apply_url"],
            "sorts": [{"propertyName": "fit_score", "direction": "DESCENDING"}], "limit": limit}) or {}

    def drafted_today(self) -> int:
        """Ready for Review deals changed since local midnight (an upper bound on
        today's drafts, so the daily cap errs on the safe side)."""
        tz = ZoneInfo(self.config.get("timezone", "UTC"))
        midnight = datetime.combine(self._now().astimezone(tz).date(), time.min, tz)
        found = self._search("Ready for Review", [{"propertyName": "hs_lastmodifieddate", "operator": "GTE",
                                                   "value": str(int(midnight.timestamp() * 1000))}], limit=1)
        return int(found.get("total", 0))

    # --- one deal --------------------------------------------------------------
    def draft_one(self, deal: dict) -> Draft:
        props = deal.get("properties", {})
        name = props.get("dealname") or deal["id"]
        company = name.split(" - ", 1)[1] if " - " in name else "Company"
        prompt = (self.draft_user
                  .replace("{job_text}", redact(strip_notes(props.get("description") or ""))[:MAX_JOB])
                  .replace("{analysis}", redact(props.get("job_analysis") or "")[:MAX_ANALYSIS])
                  .replace("{cv_pieces}", for_ai(self.master))
                  .replace("{evidence}", redact(self.master.evidence)[:3000]))
        picks = self.llm.generate_json(system=self.draft_system, prompt=prompt, schema=DRAFT_SCHEMA, role="draft")

        assembled = assemble(self.master, picks)
        problems = list(assembled.problems)
        cv = fit_two_pages(assembled.cv, problems)
        letter_raw = picks["cover_letter"]
        words = sum(len(p.split()) for p in letter_raw["paragraphs"])
        if not LETTER_WORDS[0] <= words <= LETTER_WORDS[1]:
            problems.append(f"Cover letter is {words} words (aim for {LETTER_WORDS[0]}-{LETTER_WORDS[1]}).")
        note = limit_note(picks["connection_note"], problems)
        followup = limit_followup(picks["followup_message"], problems)
        coverage = picks.get("keyword_coverage") or []
        covered = [k["requirement"] for k in coverage if k.get("covered")]
        missing = [k["requirement"] for k in coverage if not k.get("covered")]
        pct = round(100 * len(covered) / len(coverage)) if coverage else 0

        draft = Draft(deal["id"], name, company, cv, {
            "name": self.master.contact.get("name", ""),
            "contact": cv.get("contact", {}),
            "date": self.today.strftime("%d %b %Y").lstrip("0"),
            "greeting": letter_raw["greeting"], "paragraphs": letter_raw["paragraphs"],
            "closing": letter_raw["closing"]}, note, followup, pct, covered, missing, problems)
        self._truth_check(draft, assembled.used_bullets)
        self._render(draft)
        return draft

    def _truth_check(self, draft: Draft, used_bullets: dict[str, str]):
        originals = master_text_for(self.master, used_bullets)
        pairs = "\n".join(f"[{i}] SOURCE: {originals.get(i, '?')}\n      NEW: {text}" for i, text in used_bullets.items())
        letter = "\n\n".join(draft.letter["paragraphs"])
        prompt = (self.truth_user
                  .replace("{bullet_pairs}", pairs or "(none)")
                  .replace("{summary}", f"{draft.cv.get('headline', '')}\n{draft.cv.get('summary', '')}")
                  .replace("{cover_letter}", letter)
                  .replace("{connection_note}", draft.connection_note)
                  .replace("{followup}", draft.followup)
                  .replace("{source}", for_ai(self.master) + "\n\nEVIDENCE BANK:\n" + redact(self.master.evidence)))
        try:
            result = self.llm.generate_json(system=self.truth_system, prompt=prompt, schema=TRUTH_SCHEMA, role="fast")
            draft.truth_issues = result.get("issues") or []
        except LLMError as e:
            draft.truth_checked = False
            draft.problems.append(f"Truth check couldn't run ({str(e)[:100]}); review every claim by hand.")

    def _render(self, draft: Draft):
        person = self.master.contact.get("name", "Candidate")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        draft.cv_path = render_cv(draft.cv, self.out_dir / f"{file_stem(person, 'CV', draft.company)}.docx")
        draft.letter_path = render_cover_letter(
            draft.letter, self.out_dir / f"{file_stem(person, 'Cover Letter', draft.company)}.docx")

    # --- saving to HubSpot (live mode) ---------------------------------------------
    def summary_text(self, draft: Draft) -> str:
        """The private review notes for a draft (stored in HubSpot only, never logged)."""
        lines = [f"Drafts ({self.today:%d %b %Y}): CV and cover letter attached to the note on this deal."]
        if not draft.truth_checked:
            lines.append("TRUTH CHECK: NOT RUN. Review every claim by hand before using these drafts.")
        elif draft.truth_issues:
            lines.append(f"TRUTH CHECK: {len(draft.truth_issues)} issue(s) to fix before applying:")
            lines += [f"- [{i['where']}] \"{i['claim']}\": {i['problem']}" for i in draft.truth_issues]
        else:
            lines.append("Truth check: passed (every claim traced to your master CV).")
        lines.append(f"Keyword coverage: {draft.coverage_pct}%"
                     + (f" | Covered: {', '.join(draft.covered)}" if draft.covered else ""))
        if draft.missing:
            lines.append(f"Missing (don't add these unless true): {', '.join(draft.missing)}")
        lines.append(f"Connection note ({len(draft.connection_note)} chars):\n{draft.connection_note}")
        lines.append(f"Follow-up message ({len(draft.followup.split())} words):\n{draft.followup}")
        if draft.problems:
            lines.append("Draft notes:")
            lines += [f"- {p}" for p in draft.problems]
        return "\n".join(lines)

    def save(self, draft: Draft):
        """Upload both files, attach them to a note on the deal, record the review
        notes and move the deal to Ready for Review. Raises on any failure, before
        the deal moves, so nothing is half-done silently."""
        file_ids = [self.hs.upload(path.name, path.read_bytes(), FILES_FOLDER)["id"]
                    for path in (draft.cv_path, draft.letter_path)]
        summary = self.summary_text(draft)
        self.hs.post("/crm/v3/objects/notes", {
            "properties": {"hs_timestamp": self._now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "hs_note_body": html.escape(summary).replace("\n", "<br>"),
                           "hs_attachment_ids": ";".join(str(i) for i in file_ids)},
            "associations": [{"to": {"id": draft.deal_id},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                         "associationTypeId": NOTE_TO_DEAL}]}]})
        deal = self.hs.get(f"/crm/v3/objects/deals/{draft.deal_id}",
                           params={"properties": "job_analysis"}) or {}
        analysis = ((deal.get("properties") or {}).get("job_analysis") or "").split(DRAFTS_MARKER)[0].rstrip()
        flag = ""
        if not draft.truth_checked:
            flag = "TRUTH CHECK NOT RUN: review every claim in the drafts by hand, then clear this field."
        elif draft.truth_issues:
            flag = (f"TRUTH CHECK: {len(draft.truth_issues)} issue(s) in the drafts. See Job Analysis, "
                    "fix the files, then clear this field.")
        self.hs.patch(f"/crm/v3/objects/deals/{draft.deal_id}", {"properties": {
            "job_analysis": (analysis + "\n\n" + summary).strip()[:60_000],
            "keyword_coverage": draft.coverage_pct,
            "pipeline_error": flag,
            "dealstage": self.stage["Ready for Review"],
        }})

    # --- run ---------------------------------------------------------------------
    def run(self, max_ai_calls: int = 40) -> DraftReport:
        report = DraftReport()
        self._resolve()
        cap = int(self.config.get("daily_draft_cap", 20))
        report.room = max(0, cap - self.drafted_today())
        deals = self._search("Researched").get("results", [])
        for i, deal in enumerate(deals):
            props = deal.get("properties", {})
            name = props.get("dealname") or deal["id"]
            if (props.get("pipeline_error") or "").strip():
                report.skipped.append((deal["id"], name, props["pipeline_error"].split(":")[0]))
                continue
            if len(report.drafts) >= report.room or self.llm.calls + 2 > max_ai_calls:
                report.waiting = len(deals) - i
                break
            try:
                draft = self.draft_one(deal)
                if self.write:
                    try:
                        self.save(draft)
                    except HubSpotError as e:
                        self._flag(deal["id"], f"DRAFT ERROR: {str(e)[:300]}")
                        report.errors.append((deal["id"], name, f"saving to HubSpot failed: {str(e)[:200]}"))
                        continue
                report.drafts.append(draft)
            except LLMError as e:
                if e.retryable:
                    report.stopped = f"AI busy or out of quota ({e}). Remaining deals wait for the next run."
                    report.waiting = len(deals) - i
                    break
                report.errors.append((deal["id"], name, str(e)[:120]))
        report.ai_calls = self.llm.calls
        report.busy_retries = getattr(self.llm, "busy_retries", 0)
        return report

    def _flag(self, deal_id: str, message: str):
        """Mark a deal so it isn't redrafted until a human clears the flag."""
        try:
            self.hs.patch(f"/crm/v3/objects/deals/{deal_id}", {"properties": {"pipeline_error": message}})
        except HubSpotError:
            pass
