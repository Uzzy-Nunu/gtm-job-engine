"""Follow-up nudges as HubSpot tasks (PRD §10.6 DG-2).

Deals in Applied with no update for `digest.follow_up_days` (default 5) get one
HubSpot task, linked to the deal, due today. Safe to re-run: a deal that already
has an open follow-up task doesn't get another. Once Peace completes the task
(or moves the deal on), the next one can only appear after another quiet spell.

The task body holds no CV text or contact details, only the deal name and what
to do. Logs show counts only (the repo is public).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.hubspot_client import HubSpotError
from src.hubspot_schema import PIPELINE_LABEL

TASK_PREFIX = "Follow up:"
TASK_TO_DEAL = 216          # HubSpot-defined association type: task -> deal
TASK_PROPS = "hs_task_subject,hs_task_status"


@dataclass
class FollowUpReport:
    due: int = 0
    created: int = 0
    already_open: int = 0
    errors: list[str] = field(default_factory=list)
    task_deal_ids: set[str] = field(default_factory=set)   # deals that now have an open follow-up task

    def line(self, write: bool) -> str:
        verb = "created" if write else "would create"
        return (f"Follow-up tasks: {self.due} due, {self.created} {verb}, "
                f"{self.already_open} already open" + (f", {len(self.errors)} error(s)" if self.errors else ""))


class FollowUpTasks:
    def __init__(self, hubspot, config: dict, now=None):
        self.hs = hubspot
        self.days = int((config.get("digest") or {}).get("follow_up_days", 5))
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _due_deals(self, now: datetime) -> list[dict]:
        pipeline = next((p for p in self.hs.get("/crm/v3/pipelines/deals").get("results", [])
                         if p.get("label") == PIPELINE_LABEL), None)
        stage = {s["label"]: s["id"] for s in (pipeline or {}).get("stages", [])}
        if not pipeline or "Applied" not in stage:
            raise HubSpotError(404, f"Pipeline '{PIPELINE_LABEL}' or its Applied stage not found.", "SETUP",
                               "pipelines")
        cutoff = str(int((now - timedelta(days=self.days)).timestamp() * 1000))
        body = {"filterGroups": [{"filters": [
                    {"propertyName": "pipeline", "operator": "EQ", "value": pipeline["id"]},
                    {"propertyName": "dealstage", "operator": "EQ", "value": stage["Applied"]},
                    {"propertyName": "hs_lastmodifieddate", "operator": "LT", "value": cutoff}]}],
                "properties": ["dealname", "hs_lastmodifieddate"], "limit": 100,
                "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}]}
        return (self.hs.post("/crm/v3/objects/deals/search", body) or {}).get("results", [])

    def _has_open_task(self, deal_id: str) -> bool:
        linked = self.hs.get(f"/crm/v4/objects/deals/{deal_id}/associations/tasks") or {}
        for item in linked.get("results", []):
            task = self.hs.get(f"/crm/v3/objects/tasks/{item['toObjectId']}", params={"properties": TASK_PROPS})
            p = task.get("properties", {})
            if (p.get("hs_task_subject") or "").startswith(TASK_PREFIX) and p.get("hs_task_status") != "COMPLETED":
                return True
        return False

    def _create(self, deal: dict, now: datetime) -> None:
        name = deal.get("properties", {}).get("dealname") or f"Deal {deal['id']}"
        body = (f"No update on this application for {self.days}+ days. Send a short follow-up to the poster "
                "or hiring contact (the follow-up draft is in the deal's draft note), then move the deal to "
                "Followed Up. If you've heard back, move it to the right stage instead.")
        self.hs.post("/crm/v3/objects/tasks", {
            "properties": {"hs_timestamp": str(int(now.timestamp() * 1000)),
                           "hs_task_subject": f"{TASK_PREFIX} {name}"[:250],
                           "hs_task_body": body, "hs_task_status": "NOT_STARTED",
                           "hs_task_priority": "MEDIUM", "hs_task_type": "TODO"},
            "associations": [{"to": {"id": deal["id"]},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                         "associationTypeId": TASK_TO_DEAL}]}]})

    def run(self, write: bool) -> FollowUpReport:
        now = self._now()
        report = FollowUpReport()
        deals = self._due_deals(now)
        report.due = len(deals)
        for deal in deals:
            try:
                if self._has_open_task(deal["id"]):
                    report.already_open += 1
                    report.task_deal_ids.add(deal["id"])
                    continue
                if write:
                    self._create(deal, now)
                    report.task_deal_ids.add(deal["id"])
                report.created += 1
            except HubSpotError as e:
                report.errors.append(str(e))
                if e.status in (401, 403):
                    break   # missing scope: every deal would fail the same way
        return report
