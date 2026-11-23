"""Daily digest (PRD §10.6 DG-1, DG-2 listing, §10.7 OP-3).

Reads HubSpot (never writes) and builds one email:
  - deals ready for review (title, company, fit score, coverage, link)
  - deals that need you: Needs post text, truth-check flags, draft and AI errors
  - follow-ups due: deals in Applied with no update for `follow_up_days`
  - scheduled GitHub runs that failed in the last 24 hours
  - counts per stage and how many deals arrived in the last 24 hours

The email goes only to Peace. The run log shows counts only (the repo is public).
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from src.hubspot_client import HubSpotError
from src.hubspot_schema import PIPELINE_LABEL, STAGES

LIST_LIMIT = 25
CLOSED = ("Archived", "Rejected")
PROPS = ["dealname", "fit_score", "keyword_coverage", "pipeline_error", "apply_url", "hs_lastmodifieddate"]


@dataclass
class DealLine:
    id: str
    name: str
    score: str = ""
    coverage: str = ""
    flag: str = ""
    stage: str = ""
    days: int = 0
    link: str = ""


@dataclass
class Digest:
    day: str
    counts: dict[str, int] = field(default_factory=dict)
    new_24h: int = 0
    ready: list[DealLine] = field(default_factory=list)
    ready_total: int = 0
    attention: list[DealLine] = field(default_factory=list)
    attention_total: int = 0
    follow_ups: list[DealLine] = field(default_factory=list)
    follow_ups_total: int = 0
    failed_runs: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # problems building the digest itself

    # --- email ---------------------------------------------------------------
    @property
    def subject(self) -> str:
        bits = [f"{self.ready_total} ready for review"]
        if self.follow_ups_total:
            bits.append(f"{self.follow_ups_total} follow-up(s) due")
        if self.attention_total:
            bits.append(f"{self.attention_total} need you")
        if self.failed_runs:
            bits.append(f"{len(self.failed_runs)} failed run(s)")
        return f"Job digest {self.day}: " + ", ".join(bits)

    def _sections(self):
        """(title, lines) pairs shared by the text and HTML versions."""
        def deal(d: DealLine, extra: str) -> tuple[str, str]:
            return d.name, extra

        out = []
        out.append((f"Ready for review ({self.ready_total})",
                    [deal(d, " | ".join(x for x in (
                        f"fit {d.score}" if d.score else "", f"coverage {d.coverage}%" if d.coverage else "",
                        d.flag) if x)) for d in self.ready], self.ready, self.ready_total))
        out.append((f"Follow-ups due ({self.follow_ups_total})",
                    [deal(d, f"applied, no update for {d.days} days") for d in self.follow_ups],
                    self.follow_ups, self.follow_ups_total))
        out.append((f"Needs you ({self.attention_total})",
                    [deal(d, f"{d.stage}: {d.flag}") for d in self.attention], self.attention, self.attention_total))
        return out

    def text(self) -> str:
        lines = [self.subject, ""]
        for title, rows, deals, total in self._sections():
            lines.append(title.upper())
            if not rows:
                lines.append("- none")
            for (name, extra), d in zip(rows, deals):
                lines.append(f"- {name}" + (f" ({extra})" if extra else "") + (f"\n  {d.link}" if d.link else ""))
            if total > len(rows):
                lines.append(f"- ...and {total - len(rows)} more in HubSpot")
            lines.append("")
        lines.append("FAILED RUNS (LAST 24 HOURS)")
        lines += [f"- {r['name']} ({r['when']})\n  {r['url']}" for r in self.failed_runs] or ["- none"]
        lines += ["", "PIPELINE", f"- New in the last 24 hours: {self.new_24h}"]
        lines += [f"- {stage}: {n}" for stage, n in self.counts.items() if n]
        if self.notes:
            lines += ["", "DIGEST NOTES"] + [f"- {n}" for n in self.notes]
        lines += ["", "Nothing is applied or sent for you: review, approve and apply in HubSpot."]
        return "\n".join(lines)

    def html(self) -> str:
        e = html.escape
        parts = [f"<div style=\"font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#222\">"
                 f"<h2 style=\"font-size:18px\">{e(self.subject)}</h2>"]
        for title, rows, deals, total in self._sections():
            parts.append(f"<h3 style=\"font-size:15px;margin-bottom:4px\">{e(title)}</h3><ul>")
            if not rows:
                parts.append("<li>none</li>")
            for (name, extra), d in zip(rows, deals):
                label = f"<a href=\"{e(d.link)}\">{e(name)}</a>" if d.link else e(name)
                parts.append(f"<li>{label}" + (f" <span style=\"color:#666\">({e(extra)})</span>" if extra else "")
                             + "</li>")
            if total > len(rows):
                parts.append(f"<li>...and {total - len(rows)} more in HubSpot</li>")
            parts.append("</ul>")
        parts.append("<h3 style=\"font-size:15px;margin-bottom:4px\">Failed runs (last 24 hours)</h3><ul>")
        parts += [f"<li><a href=\"{e(r['url'])}\">{e(r['name'])}</a> ({e(r['when'])})</li>"
                  for r in self.failed_runs] or ["<li>none</li>"]
        parts.append("</ul><h3 style=\"font-size:15px;margin-bottom:4px\">Pipeline</h3><ul>"
                     f"<li>New in the last 24 hours: {self.new_24h}</li>")
        parts += [f"<li>{e(stage)}: {n}</li>" for stage, n in self.counts.items() if n]
        parts.append("</ul>")
        if self.notes:
            parts.append("<h3 style=\"font-size:15px\">Digest notes</h3><ul>"
                         + "".join(f"<li>{e(n)}</li>" for n in self.notes) + "</ul>")
        parts.append("<p style=\"color:#666\">Nothing is applied or sent for you: review, approve and apply "
                     "in HubSpot.</p></div>")
        return "".join(parts)

    def log_lines(self) -> list[str]:
        """Counts only: safe for public GitHub logs."""
        return [f"Ready for review: {self.ready_total} | follow-ups due: {self.follow_ups_total} | "
                f"need you: {self.attention_total} | failed runs (24 h): {len(self.failed_runs)} | "
                f"new (24 h): {self.new_24h}",
                "Stages: " + ", ".join(f"{s} {n}" for s, n in self.counts.items())] + \
               [f"! {n}" for n in self.notes]


class DigestBuilder:
    def __init__(self, hubspot, config: dict, now=None, github=None):
        self.hs = hubspot
        self.config = config
        self.tz = ZoneInfo(config.get("timezone", "UTC"))
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.github = github if github is not None else github_failed_runs
        self.follow_up_days = int((config.get("digest") or {}).get("follow_up_days", 5))
        self.stage, self.label, self.pipeline_id, self.link_base = {}, {}, None, ""

    def _resolve(self):
        for p in self.hs.get("/crm/v3/pipelines/deals").get("results", []):
            if p.get("label") == PIPELINE_LABEL:
                self.pipeline_id = p["id"]
                self.stage = {s["label"]: s["id"] for s in p.get("stages", [])}
        if not self.pipeline_id:
            raise HubSpotError(404, f"Pipeline '{PIPELINE_LABEL}' not found.", "SETUP", "pipelines")
        self.label = {v: k for k, v in self.stage.items()}
        try:
            info = self.hs.get("/account-info/v3/details") or {}
            if info.get("portalId"):
                self.link_base = (f"https://{info.get('uiDomain') or 'app.hubspot.com'}/contacts/"
                                  f"{info['portalId']}/record/0-3/")
        except HubSpotError:
            pass   # links are a nice-to-have; the digest still works without them

    def _search(self, filters, limit=LIST_LIMIT, sort="fit_score", direction="DESCENDING"):
        body = {"filterGroups": [{"filters": [{"propertyName": "pipeline", "operator": "EQ",
                                               "value": self.pipeline_id}] + filters}],
                "properties": PROPS + ["dealstage"], "limit": limit,
                "sorts": [{"propertyName": sort, "direction": direction}]}
        return self.hs.post("/crm/v3/objects/deals/search", body) or {}

    def _line(self, deal: dict) -> DealLine:
        p = deal.get("properties", {})
        score = p.get("fit_score") or ""
        cov = p.get("keyword_coverage") or ""
        return DealLine(id=deal["id"], name=p.get("dealname") or f"Deal {deal['id']}",
                        score=str(score).split(".")[0], coverage=str(cov).split(".")[0],
                        flag=(p.get("pipeline_error") or "").split(":")[0].strip(),
                        stage=self.label.get(p.get("dealstage"), ""),
                        link=self.link_base + deal["id"] if self.link_base else "")

    @staticmethod
    def _ms(when: datetime) -> str:
        return str(int(when.timestamp() * 1000))

    def build(self) -> Digest:
        self._resolve()
        now = self._now()
        digest = Digest(day=now.astimezone(self.tz).strftime("%a %d %b"))

        for label, _ in STAGES:
            if label in self.stage:
                found = self._search([{"propertyName": "dealstage", "operator": "EQ", "value": self.stage[label]}],
                                     limit=1)
                digest.counts[label] = int(found.get("total", 0))

        found = self._search([{"propertyName": "createdate", "operator": "GTE",
                               "value": self._ms(now - timedelta(hours=24))}], limit=1)
        digest.new_24h = int(found.get("total", 0))

        found = self._search([{"propertyName": "dealstage", "operator": "EQ",
                               "value": self.stage.get("Ready for Review")}])
        digest.ready = [self._line(d) for d in found.get("results", [])]
        digest.ready_total = int(found.get("total", len(digest.ready)))

        if "Applied" in self.stage:
            cutoff = now - timedelta(days=self.follow_up_days)
            found = self._search([{"propertyName": "dealstage", "operator": "EQ", "value": self.stage["Applied"]},
                                  {"propertyName": "hs_lastmodifieddate", "operator": "LT",
                                   "value": self._ms(cutoff)}],
                                 sort="hs_lastmodifieddate", direction="ASCENDING")
            for d in found.get("results", []):
                line = self._line(d)
                changed = d.get("properties", {}).get("hs_lastmodifieddate")
                if changed:
                    line.days = (now - _as_datetime(changed)).days
                digest.follow_ups.append(line)
            digest.follow_ups_total = int(found.get("total", len(digest.follow_ups)))

        found = self._search([{"propertyName": "pipeline_error", "operator": "HAS_PROPERTY"}],
                             limit=100, sort="hs_lastmodifieddate", direction="DESCENDING")
        open_flags = [self._line(d) for d in found.get("results", [])]
        open_flags = [d for d in open_flags if d.stage not in CLOSED and d.flag]
        digest.attention = open_flags[:LIST_LIMIT]
        digest.attention_total = len(open_flags)

        try:
            digest.failed_runs = self.github(now - timedelta(hours=24), self.tz)
        except Exception as e:  # noqa: BLE001 - a GitHub hiccup must not stop the digest
            digest.notes.append(f"Couldn't check GitHub for failed runs ({type(e).__name__}).")
        return digest


def _as_datetime(value) -> datetime:
    text = str(value)
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def github_failed_runs(since: datetime, tz, session=None) -> list[dict]:
    """Failed workflow runs in this repo since `since` (needs GITHUB_TOKEN and
    GITHUB_REPOSITORY, which GitHub Actions provides). Empty when run locally."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return []
    s = session or requests
    resp = s.get(f"https://api.github.com/repos/{repo}/actions/runs",
                 params={"status": "failure", "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                         "per_page": 20},
                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                 timeout=30)
    resp.raise_for_status()
    runs = []
    for r in resp.json().get("workflow_runs", []):
        when = _as_datetime(r.get("created_at", "1970-01-01T00:00:00Z")).astimezone(tz)
        runs.append({"name": r.get("name") or "Workflow", "url": r.get("html_url", ""),
                     "when": when.strftime("%a %H:%M")})
    return runs
