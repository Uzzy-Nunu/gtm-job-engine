"""Qualify step (PRD §10.2): New deals -> Qualified or Archived.

For each deal in "New" (oldest first):
  1. Job text: the deal description, or, if that's only a snippet, the job's
     own page via its apply link (never LinkedIn; robots.txt respected).
  2. Redact contact details, then ask the AI for the facts and a fit judgement
     (prompts/qualify.md, JSON schema below; poster details are never asked for).
  3. Hard filters and the rubric score are applied by code (src/scoring.py).
  4. The deal is renamed "Job Title - Company", scored, analysed, linked to its
     company and moved to Qualified or Archived.

Deals with a Pipeline Error (e.g. NEEDS POST TEXT) are skipped until a human
clears it. If the AI is busy or out of quota, the run stops cleanly and the
remaining deals wait for the next run (re-runs are safe: only "New" is read).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit

from src.hubspot_client import HubSpotError
from src.hubspot_schema import PIPELINE_LABEL
from src.llm import LLMError
from src.redact import redact, strip_notes
from src.scoring import analysis_text, score
from src.sources.base import USER_AGENT, html_to_text
from src.urls import URLError, company_domain, is_linkedin, normalise_url

ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = ROOT / "prompts" / "qualify.md"
MIN_TEXT = 150         # below this there's nothing to judge
FETCH_BELOW = 400      # below this, try the job's own page for the full description
MAX_JOB_TEXT = 15_000  # characters sent to the AI

_STR_OR_NULL = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMA = {
    "type": "object",
    "required": ["job_title", "company_name", "remote_scope", "seniority", "required_skills",
                 "tools_mentioned", "key_requirements", "skills_overlap_points",
                 "senior_requirements_met", "matched_skills", "missing_requirements", "fit_reasons"],
    "properties": {
        "job_title": {"type": "string"},
        "company_name": _STR_OR_NULL,
        "company_domain": _STR_OR_NULL,
        "apply_url": _STR_OR_NULL,
        "remote_scope": {"type": "string", "enum": ["Worldwide", "Region", "Country-restricted", "Unclear", "Not remote"]},
        "eligible_regions": _STR_OR_NULL,
        "seniority": {"type": "string", "enum": ["Entry", "Mid", "Senior", "Lead", "Unclear"]},
        "salary_text": _STR_OR_NULL,
        "required_skills": _LIST,
        "tools_mentioned": _LIST,
        "key_requirements": _LIST,
        "skills_overlap_points": {"type": "integer", "minimum": 0, "maximum": 20},
        "senior_requirements_met": {"type": "boolean"},
        "matched_skills": _LIST,
        "missing_requirements": _LIST,
        "fit_reasons": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
    },
}


def load_prompt(path: Path = PROMPT_FILE) -> tuple[str, str]:
    """(system, user) from a prompt file with '## SYSTEM' and '## USER' heading lines."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r"^## SYSTEM[ \t]*\n(.*?)^## USER[ \t]*\n(.*)\Z", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"{path.name} needs '## SYSTEM' and '## USER' heading lines.")
    return match.group(1).strip(), match.group(2).strip()


@dataclass
class Outcome:
    deal_id: str
    old_name: str
    new_name: str
    status: str            # Qualified | Archived | skipped | error
    score: int | None = None
    reason: str = ""


@dataclass
class QualifyReport:
    outcomes: list[Outcome] = field(default_factory=list)
    waiting: int = 0       # New deals left for the next run
    stopped: str | None = None
    ai_calls: int = 0

    def count(self, status):
        return sum(1 for o in self.outcomes if o.status == status)

    @property
    def ok(self) -> bool:
        return self.count("error") == 0 and not self.stopped

    def lines(self) -> list[str]:
        out = [f"Qualified: {self.count('Qualified')} | Archived: {self.count('Archived')} | "
               f"skipped: {self.count('skipped')} | errors: {self.count('error')} | "
               f"AI requests: {self.ai_calls} | left for next run: {self.waiting}"]
        if self.stopped:
            out.append(f"! Stopped early: {self.stopped}")
        for o in self.outcomes:
            score_txt = f"{o.score:>3}" if o.score is not None else "  -"
            out.append(f"  {o.status:<9} {score_txt}  {public_name(o.new_name, o.deal_id)}"
                       + (f"  ({o.reason})" if o.reason else ""))
        return out


def public_name(name: str, deal_id: str) -> str:
    """Logs on a public repo are public: never print a poster's name."""
    if name.startswith("LinkedIn post by"):
        return f"LinkedIn post (#{deal_id})"
    return name


class Qualifier:
    def __init__(self, hubspot, llm, config: dict, profile: str, http=None,
                 write: bool = True, today: date | None = None, robots_ok=None):
        self.hs = hubspot
        self.llm = llm
        self.config = config
        self.profile = profile
        self.http = http
        self.write = write
        self.today = today or date.today()
        self.robots_ok = robots_ok or _robots_allows
        self.system, self.user_template = load_prompt()
        self.stage = {}
        self.pipeline_id = None

    # --- HubSpot helpers --------------------------------------------------
    def _resolve(self):
        for p in self.hs.get("/crm/v3/pipelines/deals").get("results", []):
            if p.get("label") == PIPELINE_LABEL:
                self.pipeline_id = p["id"]
                self.stage = {s["label"]: s["id"] for s in p.get("stages", [])}
        missing = [s for s in ("New", "Qualified", "Archived") if s not in self.stage]
        if not self.pipeline_id or missing:
            raise HubSpotError(404, f"Pipeline '{PIPELINE_LABEL}' or stages {missing} not found. "
                                    "Run Setup HubSpot first.", "SETUP", "pipelines")

    def new_deals(self) -> list[dict]:
        found = self.hs.post("/crm/v3/objects/deals/search", {
            "filterGroups": [{"filters": [
                {"propertyName": "pipeline", "operator": "EQ", "value": self.pipeline_id},
                {"propertyName": "dealstage", "operator": "EQ", "value": self.stage["New"]},
            ]}],
            "properties": ["dealname", "description", "apply_url", "job_url", "job_source", "pipeline_error"],
            "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
            "limit": 100,
        })
        return (found or {}).get("results", [])

    def _update(self, deal_id: str, props: dict):
        if self.write:
            self.hs.patch(f"/crm/v3/objects/deals/{deal_id}", {"properties": props})

    # --- job text -----------------------------------------------------------
    def job_text(self, props: dict) -> str:
        text = strip_notes(props.get("description") or "").strip()
        url = props.get("apply_url") or ""
        if len(text) < FETCH_BELOW and url and self.http is not None and not is_linkedin(url):
            try:
                if self.robots_ok(url):
                    page = html_to_text(self.http.text(url))
                    if len(page) > len(text):
                        text = (text + "\n\n" + page).strip()
            except Exception:  # noqa: BLE001 - a missing page just means less text
                pass
        return text

    # --- main ---------------------------------------------------------------
    def run(self, max_ai_calls: int = 40) -> QualifyReport:
        report = QualifyReport()
        self._resolve()
        deals = self.new_deals()
        for i, deal in enumerate(deals):
            props = deal.get("properties", {})
            name = props.get("dealname") or deal["id"]
            if (props.get("pipeline_error") or "").strip():
                report.outcomes.append(Outcome(deal["id"], name, name, "skipped",
                                               reason=(props["pipeline_error"].split(":")[0])))
                continue
            if self.llm.calls >= max_ai_calls:
                report.waiting = len(deals) - i
                break
            text = self.job_text(props)
            if len(text) < MIN_TEXT:
                self._update(deal["id"], {"pipeline_error":
                    "JOB TEXT TOO SHORT: paste the job description into 'Deal description' and clear this field."})
                report.outcomes.append(Outcome(deal["id"], name, name, "skipped", reason="job text too short"))
                continue
            try:
                facts = self.llm.generate_json(system=self.system, prompt=self._prompt(text),
                                               schema=SCHEMA, role="fast")
            except LLMError as e:
                if e.retryable:
                    report.stopped = f"AI busy or out of quota ({e}). Remaining deals wait for the next run."
                    report.waiting = len(deals) - i
                    break
                self._update(deal["id"], {"pipeline_error": f"AI ERROR: {str(e)[:400]}"})
                report.outcomes.append(Outcome(deal["id"], name, name, "error", reason=str(e)[:120]))
                continue
            report.outcomes.append(self._apply(deal, props, facts))
        report.ai_calls = self.llm.calls
        return report

    def _prompt(self, text: str) -> str:
        return (self.user_template
                .replace("{today}", self.today.isoformat())
                .replace("{profile}", self.profile)
                .replace("{job_text}", redact(text)[:MAX_JOB_TEXT]))

    def _apply(self, deal: dict, props: dict, facts: dict) -> Outcome:
        threshold = int(self.config.get("fit_threshold", 70))
        verdict = score(facts, self.config)
        old = props.get("dealname") or deal["id"]
        title = (facts.get("job_title") or "").strip()
        company = (facts.get("company_name") or "").strip()
        new = f"{title} - {company}" if title and company else (f"{title} - company TBC" if title else old)
        status = "Qualified" if verdict.qualified else "Archived"
        update = {
            "dealname": new[:250],
            "fit_score": verdict.score,
            "remote_scope": facts.get("remote_scope"),
            "job_analysis": analysis_text(facts, verdict, threshold)[:60_000],
            "dealstage": self.stage[status],
        }
        apply_url = _clean_url(facts.get("apply_url"))
        if apply_url and not props.get("apply_url"):
            update["apply_url"] = apply_url
        self._update(deal["id"], update)
        if company and self.write:
            self._link_company(deal["id"], company, facts.get("company_domain"), apply_url or props.get("apply_url"))
        return Outcome(deal["id"], old, new, status, verdict.score,
                       "" if verdict.qualified else (verdict.archive_reason or ""))

    def _link_company(self, deal_id, name, domain, apply_url):
        domain = _clean_domain(domain) or _domain_from(apply_url)
        found = None
        for prop, value in (("domain", domain), ("name", name)):
            if value:
                hits = self.hs.post("/crm/v3/objects/companies/search", {
                    "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
                    "limit": 1}).get("results", [])
                if hits:
                    found = hits[0]["id"]
                    break
        if not found:
            props = {"name": name}
            if domain:
                props["domain"] = domain
            found = self.hs.post("/crm/v3/objects/companies", {"properties": props})["id"]
        self.hs.put(f"/crm/v4/objects/deals/{deal_id}/associations/default/companies/{found}")


def _clean_url(url) -> str | None:
    if not url or is_linkedin(str(url)):
        return None
    try:
        return normalise_url(str(url))
    except URLError:
        return None


def _clean_domain(domain) -> str | None:
    if not domain:
        return None
    domain = re.sub(r"^https?://", "", str(domain).strip().lower()).split("/")[0]
    domain = domain[4:] if domain.startswith("www.") else domain
    return domain if "." in domain and " " not in domain else None


def _domain_from(url) -> str | None:
    try:
        return company_domain(url) if url else None
    except URLError:
        return None


def _robots_allows(url: str) -> bool:
    parts = urlsplit(url)
    rp = robotparser.RobotFileParser(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:  # noqa: BLE001 - no robots.txt means no restrictions stated
        return True
    return rp.can_fetch(USER_AGENT, url)
