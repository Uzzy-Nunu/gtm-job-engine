"""Weekly summary, sent on Mondays (PRD §10.6 DG-3): the funnel numbers in §3.

Reads HubSpot (never writes). The free CRM keeps no stage history, so the numbers
come from what each deal holds today:
  - arrived: deals created in the last 7 days
  - qualified rate: of those that have been through qualification, the share
    that wasn't archived (target 20-40%)
  - applied: deals with an Applied Date in the last 7 days (target 5 per weekday)
  - keyword coverage: average across drafted deals, and the share at 80% or more
  - truth check: drafted deals with an open TRUTH CHECK flag
  - interview rate: Interviewing + Offer, out of every deal that was applied for
  - failed GitHub runs in the last 7 days (up to 20)
It holds numbers only (no deal names), so the log and email show the same thing.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.digest import github_failed_runs
from src.hubspot_client import HubSpotError
from src.hubspot_schema import PIPELINE_LABEL, STAGES

APPLIED_OR_LATER = ("Applied", "Followed Up", "Interviewing", "Offer", "Rejected")
PAST_QUALIFY = ("Qualified", "Researched", "Ready for Review", "Approved") + APPLIED_OR_LATER
DEFAULT_GOALS = {"go_live_per_day": 5, "target_per_day": 15, "streak_days": 5}   # PRD §17 M7 and M9


def _streak(per_day: dict, days: list, minimum: int) -> int:
    """Longest run of consecutive working days (in `days` order) with >= minimum applications."""
    best = run = 0
    for day in days:
        run = run + 1 if per_day.get(day, 0) >= minimum else 0
        best = max(best, run)
    return best
COVERAGE_TARGET = 80


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "n/a"


@dataclass
class Weekly:
    period: str
    arrived: int = 0
    arrived_qualified: int = 0
    arrived_archived: int = 0
    arrived_waiting: int = 0
    applied: int = 0
    per_day: dict = field(default_factory=dict)       # working day (YYYY-MM-DD) -> applications
    working_days: list = field(default_factory=list)
    goals: dict = field(default_factory=lambda: dict(DEFAULT_GOALS))
    drafted: int = 0
    coverage_avg: float | None = None
    coverage_at_target: int = 0
    truth_flagged: int = 0
    ever_applied: int = 0
    interviewing: int = 0
    offers: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    failed_runs: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def subject(self) -> str:
        return f"Weekly job summary {self.period}: {self.applied} applied, {self.arrived} new jobs"

    def rows(self) -> list[tuple[str, list[str]]]:
        processed = self.arrived_qualified + self.arrived_archived
        cov = f"{self.coverage_avg:.0f}%" if self.coverage_avg is not None else "n/a"
        return [
            ("This week", [
                f"New jobs in: {self.arrived}",
                f"Qualified rate: {_pct(self.arrived_qualified, processed)} "
                f"({self.arrived_qualified} of {processed} processed; target 20-40%)"
                + (f"; {self.arrived_waiting} still waiting" if self.arrived_waiting else ""),
                f"Applied: {self.applied} (goal {self.goals['target_per_day'] * 5}: "
                f"{self.goals['target_per_day']} per weekday)",
                f"Failed GitHub runs: {self.failed_runs}",
            ]),
            ("Milestone progress (working days this week)", self.milestone_lines()),
            ("Draft quality (all drafted deals)", [
                f"Drafted: {self.drafted}",
                f"Average keyword coverage: {cov}; {_pct(self.coverage_at_target, self.drafted)} at "
                f"{COVERAGE_TARGET}% or more",
                f"Open truth-check flags: {self.truth_flagged} "
                f"(pass rate {_pct(self.drafted - self.truth_flagged, self.drafted)}; scale-up needs 90%)",
            ]),
            ("Outcomes (all time)", [
                f"Applied for: {self.ever_applied}",
                f"Interviewing or offer: {self.interviewing + self.offers} "
                f"(interview rate {_pct(self.interviewing + self.offers, self.ever_applied)})",
                f"Rejected: {self.counts.get('Rejected', 0)}",
            ]),
            ("Pipeline now", [f"{s}: {n}" for s, n in self.counts.items() if n] or ["empty"]),
        ]

    def milestone_lines(self) -> list[str]:
        g = self.goals
        daily = ", ".join(f"{d[5:]} {self.per_day.get(d, 0)}" for d in self.working_days) or "none"
        out = [f"Applications per working day: {daily}"]
        for label, key in (("M7 go live", "go_live_per_day"), ("M9 hold 15 a day", "target_per_day")):
            streak = _streak(self.per_day, self.working_days, g[key])
            done = " (met)" if streak >= g["streak_days"] else ""
            out.append(f"{label}: {streak} of {g['streak_days']} days in a row at {g[key]}+{done}")
        return out

    def text(self) -> str:
        out = [self.subject, ""]
        for title, lines in self.rows():
            out += [title.upper()] + [f"- {x}" for x in lines] + [""]
        if self.notes:
            out += ["NOTES"] + [f"- {n}" for n in self.notes] + [""]
        out.append("Numbers come from each deal's current stage and dates (the free CRM keeps no stage history).")
        return "\n".join(out)

    def html(self) -> str:
        e = html.escape
        parts = ["<div style=\"font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#222\">"
                 f"<h2 style=\"font-size:18px\">{e(self.subject)}</h2>"]
        for title, lines in self.rows():
            parts.append(f"<h3 style=\"font-size:15px;margin-bottom:4px\">{e(title)}</h3><ul>"
                         + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ul>")
        if self.notes:
            parts.append("<h3 style=\"font-size:15px\">Notes</h3><ul>"
                         + "".join(f"<li>{e(n)}</li>" for n in self.notes) + "</ul>")
        parts.append("<p style=\"color:#666\">Numbers come from each deal's current stage and dates "
                     "(the free CRM keeps no stage history).</p></div>")
        return "".join(parts)

    def log_lines(self) -> list[str]:
        return [x for _, lines in self.rows() for x in lines] + [f"! {n}" for n in self.notes]


class WeeklyBuilder:
    def __init__(self, hubspot, config: dict, now=None, github=None):
        self.hs = hubspot
        self.tz = ZoneInfo(config.get("timezone", "UTC"))
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.github = github if github is not None else github_failed_runs
        self.goals = dict(DEFAULT_GOALS, **(config.get("goals") or {}))
        self.pipeline_id, self.stage = None, {}

    def _resolve(self):
        for p in self.hs.get("/crm/v3/pipelines/deals").get("results", []):
            if p.get("label") == PIPELINE_LABEL:
                self.pipeline_id = p["id"]
                self.stage = {s["label"]: s["id"] for s in p.get("stages", [])}
        if not self.pipeline_id:
            raise HubSpotError(404, f"Pipeline '{PIPELINE_LABEL}' not found.", "SETUP", "pipelines")

    def _filters(self, extra):
        return [{"filters": [{"propertyName": "pipeline", "operator": "EQ", "value": self.pipeline_id}] + extra}]

    def _count(self, extra) -> int:
        body = {"filterGroups": self._filters(extra), "properties": ["dealstage"], "limit": 1}
        return int((self.hs.post("/crm/v3/objects/deals/search", body) or {}).get("total", 0))

    def _all(self, extra, props) -> list[dict]:
        out, after = [], None
        while True:
            body = {"filterGroups": self._filters(extra), "properties": props, "limit": 100,
                    "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}]}
            if after:
                body["after"] = after
            page = self.hs.post("/crm/v3/objects/deals/search", body) or {}
            out += page.get("results", [])
            after = ((page.get("paging") or {}).get("next") or {}).get("after")
            if not after or len(out) >= 10000:   # HubSpot search stops at 10,000 results
                return out

    def _stage_in(self, labels) -> dict:
        return {"propertyName": "dealstage", "operator": "IN",
                "values": [self.stage[x] for x in labels if x in self.stage]}

    def build(self) -> Weekly:
        self._resolve()
        now = self._now()
        start = now - timedelta(days=7)
        local = lambda d: d.astimezone(self.tz).strftime("%d %b")  # noqa: E731
        w = Weekly(period=f"{local(start)} - {local(now)}")
        ms = str(int(start.timestamp() * 1000))

        for label, _ in STAGES:
            if label in self.stage:
                w.counts[label] = self._count([{"propertyName": "dealstage", "operator": "EQ",
                                                "value": self.stage[label]}])

        label_of = {v: k for k, v in self.stage.items()}
        for d in self._all([{"propertyName": "createdate", "operator": "GTE", "value": ms}], ["dealstage"]):
            stage = label_of.get(d.get("properties", {}).get("dealstage"), "")
            w.arrived += 1
            if stage in PAST_QUALIFY:
                w.arrived_qualified += 1
            elif stage == "Archived":
                w.arrived_archived += 1
            else:
                w.arrived_waiting += 1

        w.goals = self.goals
        first = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        applied = self._all([{"propertyName": "applied_date", "operator": "GTE",
                              "value": str(int(first.timestamp() * 1000))}], ["applied_date"])
        w.applied = len(applied)
        for d in applied:
            day = str((d.get("properties") or {}).get("applied_date") or "")[:10]
            if day.isdigit():   # epoch ms
                day = datetime.fromtimestamp(int(day) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            w.per_day[day] = w.per_day.get(day, 0) + 1
        w.working_days = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(8)
                          if (first + timedelta(days=i)).weekday() < 5 and first + timedelta(days=i) <= now]

        drafted = self._all([{"propertyName": "keyword_coverage", "operator": "HAS_PROPERTY"}],
                            ["keyword_coverage", "pipeline_error"])
        values = []
        for d in drafted:
            p = d.get("properties", {})
            try:
                values.append(float(p.get("keyword_coverage")))
            except (TypeError, ValueError):
                continue
            if (p.get("pipeline_error") or "").startswith("TRUTH CHECK"):
                w.truth_flagged += 1
        w.drafted = len(values)
        if values:
            w.coverage_avg = sum(values) / len(values)
            w.coverage_at_target = sum(1 for v in values if v >= COVERAGE_TARGET)

        w.ever_applied = sum(w.counts.get(s, 0) for s in APPLIED_OR_LATER)
        w.interviewing, w.offers = w.counts.get("Interviewing", 0), w.counts.get("Offer", 0)
        if w.applied == 0 and w.counts.get("Applied", 0):
            w.notes.append("Deals are in Applied but none has an Applied Date this week: set Applied Date "
                           "when you apply so this count is right.")

        try:
            w.failed_runs = len(self.github(start, self.tz))
        except Exception as e:  # noqa: BLE001 - a GitHub hiccup must not stop the summary
            w.notes.append(f"Couldn't check GitHub for failed runs ({type(e).__name__}).")
        return w
