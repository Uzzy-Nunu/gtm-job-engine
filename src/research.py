"""Research step (PRD §10.3): Qualified deals -> Researched.

For each Qualified deal (highest Fit Score first):
  1. Find its company and read the company's own homepage (and /about if the
     homepage says little). Public pages only, robots.txt respected, never
     LinkedIn.
  2. Redact, then ask the AI for a 3-5 bullet brief, a cover-letter angle and
     2-3 hiring-manager titles to look up by hand (titles only, never names).
  3. Save the brief on the company (Description, if empty) and in the deal's
     Job Analysis, then move the deal to Researched.

Same safety as Qualify: deals with a Pipeline Error are skipped, the run stops
cleanly if the AI is busy, preview mode writes nothing, and logs never print
poster names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.hubspot_client import HubSpotError
from src.hubspot_schema import PIPELINE_LABEL
from src.llm import LLMError
from src.qualify import _robots_allows, load_prompt, public_name
from src.redact import redact, strip_notes
from src.sources.base import html_to_text
from src.urls import is_linkedin

ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = ROOT / "prompts" / "research.md"
MAX_WEBSITE = 8_000
MAX_JOB = 6_000
SHORT_HOMEPAGE = 600   # below this, also read /about
BRIEF_MARKER = "\n\nCompany brief:"

SCHEMA = {
    "type": "object",
    "required": ["brief_bullets", "cover_letter_angle", "suggested_contact_titles", "website_was_useful"],
    "properties": {
        "brief_bullets": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 5},
        "cover_letter_angle": {"type": "string"},
        "suggested_contact_titles": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3},
        "website_was_useful": {"type": "boolean"},
    },
}


@dataclass
class ResearchOutcome:
    deal_id: str
    name: str
    status: str            # Researched | skipped | error
    note: str = ""


@dataclass
class ResearchReport:
    outcomes: list[ResearchOutcome] = field(default_factory=list)
    waiting: int = 0
    stopped: str | None = None
    ai_calls: int = 0
    busy_retries: int = 0

    def count(self, status):
        return sum(1 for o in self.outcomes if o.status == status)

    @property
    def ok(self) -> bool:
        return self.count("error") == 0 and not self.stopped

    def lines(self) -> list[str]:
        out = [f"Researched: {self.count('Researched')} | skipped: {self.count('skipped')} | "
               f"errors: {self.count('error')} | AI requests: {self.ai_calls} "
               f"(busy retries: {self.busy_retries}) | left for next run: {self.waiting}"]
        if self.stopped:
            out.append(f"! Stopped early: {self.stopped}")
        for o in self.outcomes:
            out.append(f"  {o.status:<10} {public_name(o.name, o.deal_id)}" + (f"  ({o.note})" if o.note else ""))
        return out


def brief_text(answer: dict) -> str:
    lines = ["Company brief:"] + [f"- {b}" for b in answer["brief_bullets"]]
    lines.append(f"Cover letter angle: {answer['cover_letter_angle']}")
    lines.append("Suggested contacts to look up (titles): " + ", ".join(answer["suggested_contact_titles"]))
    if not answer.get("website_was_useful"):
        lines.append("(Based on the job posting only: the company website gave little to go on.)")
    return "\n".join(lines)


class Researcher:
    def __init__(self, hubspot, llm, config: dict, http=None, write: bool = True, robots_ok=None):
        self.hs = hubspot
        self.llm = llm
        self.config = config
        self.http = http
        self.write = write
        self.robots_ok = robots_ok or _robots_allows
        self.system, self.user_template = load_prompt(PROMPT_FILE)
        self.stage = {}
        self.pipeline_id = None

    def _resolve(self):
        for p in self.hs.get("/crm/v3/pipelines/deals").get("results", []):
            if p.get("label") == PIPELINE_LABEL:
                self.pipeline_id = p["id"]
                self.stage = {s["label"]: s["id"] for s in p.get("stages", [])}
        missing = [s for s in ("Qualified", "Researched") if s not in self.stage]
        if not self.pipeline_id or missing:
            raise HubSpotError(404, f"Pipeline '{PIPELINE_LABEL}' or stages {missing} not found.", "SETUP", "pipelines")

    def qualified_deals(self) -> list[dict]:
        found = self.hs.post("/crm/v3/objects/deals/search", {
            "filterGroups": [{"filters": [
                {"propertyName": "pipeline", "operator": "EQ", "value": self.pipeline_id},
                {"propertyName": "dealstage", "operator": "EQ", "value": self.stage["Qualified"]},
            ]}],
            "properties": ["dealname", "description", "apply_url", "job_analysis", "pipeline_error", "fit_score"],
            "sorts": [{"propertyName": "fit_score", "direction": "DESCENDING"}],
            "limit": 100,
        })
        return (found or {}).get("results", [])

    def company_of(self, deal_id: str) -> dict:
        links = self.hs.get(f"/crm/v4/objects/deals/{deal_id}/associations/companies") or {}
        results = links.get("results") or []
        if not results:
            return {}
        company_id = str(results[0].get("toObjectId"))
        record = self.hs.get(f"/crm/v3/objects/companies/{company_id}",
                             params={"properties": "name,domain,description"})
        return {"id": company_id, **(record or {}).get("properties", {})}

    def website_text(self, domain: str | None) -> str:
        if not domain or self.http is None:
            return ""
        base = f"https://{domain.strip().lower().removeprefix('www.')}"
        if is_linkedin(base):
            return ""
        text = ""
        for path in ("", "/about"):
            url = base + path
            try:
                if not self.robots_ok(url):
                    continue
                page = html_to_text(self.http.text(url))
            except Exception:  # noqa: BLE001 - a missing page just means less context
                continue
            text = (text + "\n\n" + page).strip()
            if len(text) >= SHORT_HOMEPAGE:
                break
        return text[:MAX_WEBSITE]

    def run(self, max_ai_calls: int = 40) -> ResearchReport:
        report = ResearchReport()
        self._resolve()
        deals = self.qualified_deals()
        for i, deal in enumerate(deals):
            props = deal.get("properties", {})
            name = props.get("dealname") or deal["id"]
            if (props.get("pipeline_error") or "").strip():
                report.outcomes.append(ResearchOutcome(deal["id"], name, "skipped",
                                                       props["pipeline_error"].split(":")[0]))
                continue
            if self.llm.calls >= max_ai_calls:
                report.waiting = len(deals) - i
                break
            company = self.company_of(deal["id"])
            company_name = company.get("name") or (name.split(" - ", 1)[1] if " - " in name else "unknown")
            website = self.website_text(company.get("domain"))
            prompt = (self.user_template
                      .replace("{company}", company_name)
                      .replace("{website}", redact(website) or "(no website text available)")
                      .replace("{job_text}", redact(strip_notes(props.get("description") or ""))[:MAX_JOB]))
            try:
                answer = self.llm.generate_json(system=self.system, prompt=prompt, schema=SCHEMA, role="fast")
            except LLMError as e:
                if e.retryable:
                    report.stopped = f"AI busy or out of quota ({e}). Remaining deals wait for the next run."
                    report.waiting = len(deals) - i
                    break
                if self.write:
                    self.hs.patch(f"/crm/v3/objects/deals/{deal['id']}",
                                  {"properties": {"pipeline_error": f"AI ERROR (research): {str(e)[:400]}"}})
                report.outcomes.append(ResearchOutcome(deal["id"], name, "error", str(e)[:120]))
                continue
            self._save(deal, props, company, answer)
            note = "" if answer.get("website_was_useful") else "brief from job posting only"
            report.outcomes.append(ResearchOutcome(deal["id"], name, "Researched", note))
        report.ai_calls = self.llm.calls
        report.busy_retries = getattr(self.llm, "busy_retries", 0)
        return report

    def _save(self, deal, props, company, answer):
        if not self.write:
            return
        brief = brief_text(answer)
        analysis = (props.get("job_analysis") or "").split(BRIEF_MARKER)[0].rstrip()
        self.hs.patch(f"/crm/v3/objects/deals/{deal['id']}", {"properties": {
            "job_analysis": (analysis + "\n\n" + brief).strip()[:60_000],
            "dealstage": self.stage["Researched"],
        }})
        if company.get("id") and not (company.get("description") or "").strip():
            summary = re.sub(r"\s+", " ", " ".join(answer["brief_bullets"]))[:1000]
            self.hs.patch(f"/crm/v3/objects/companies/{company['id']}", {"properties": {"description": summary}})
