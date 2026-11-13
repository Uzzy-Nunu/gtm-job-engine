"""Set up HubSpot for GTM Job Engine (Milestone 1, PRD §9).

What it does:
- renames the free CRM's one deal pipeline to "Job Applications"
- makes its stages match PRD §9.1 (reuses and renames default stages, adds
  missing ones, removes leftover *empty* default stages)
- creates the "GTM Job Engine" deal property group and 9 custom deal properties
- checks the built-in contact "LinkedIn URL" property exists

Safety:
- Default mode is a read-only PLAN: it reads HubSpot and prints every change
  it would make, and writes nothing.
- Add --apply to make the changes. Re-running is safe: anything already set
  up is left alone.
- It stops before writing anything if the free-plan custom property limit
  would be exceeded, or if the pipeline already holds deals.

Usage:
  python scripts/setup_hubspot.py            # plan only (read-only)
  python scripts/setup_hubspot.py --apply    # make the changes
  python scripts/setup_hubspot.py --offline  # print the target model, no HubSpot calls
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.hubspot_client import HubSpotClient, HubSpotError, load_dotenv  # noqa: E402
from src.hubspot_schema import (CONTACT_LINKEDIN_PROPERTY, COUNTED_OBJECTS,  # noqa: E402
                                DEAL_PROPERTIES, DEAL_PROPERTY_GROUP,
                                PIPELINE_LABEL, STAGES)

PIPELINES = "/crm/v3/pipelines/deals"
PROPS = "/crm/v3/properties"


@dataclass
class Plan:
    actions: list[tuple[str, Callable[[], object]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def add(self, description: str, fn: Callable[[], object]) -> None:
        self.actions.append((description, fn))


def _prob(stage) -> float | None:
    try:
        return float((stage.get("metadata") or {}).get("probability"))
    except (TypeError, ValueError):
        return None


def _custom_property_names(client, obj: str) -> list[str]:
    results = client.get(f"{PROPS}/{obj}").get("results", [])
    return [p["name"] for p in results
            if not p.get("hubspotDefined") and not p.get("archived")]


def _pick_pipeline(pipelines: list[dict]) -> dict | None:
    for p in pipelines:
        if p.get("label", "").strip().lower() == PIPELINE_LABEL.lower():
            return p
    for p in pipelines:
        if p.get("id") == "default":
            return p
    return pipelines[0] if pipelines else None


def plan_pipeline(client, plan: Plan) -> None:
    pipelines = client.get(PIPELINES).get("results", [])
    pipeline = _pick_pipeline(pipelines)
    if pipeline is None:
        plan.blockers.append("No deal pipeline found in this HubSpot account.")
        return
    pid = pipeline["id"]

    if pipeline.get("label") != PIPELINE_LABEL:
        plan.add(f"Rename pipeline '{pipeline.get('label')}' -> '{PIPELINE_LABEL}'",
                 lambda: client.patch(f"{PIPELINES}/{pid}", {"label": PIPELINE_LABEL}))
    else:
        plan.notes.append(f"Pipeline '{PIPELINE_LABEL}' already exists.")

    existing = sorted(pipeline.get("stages", []), key=lambda s: s.get("displayOrder", 0))
    by_label = {s["label"].strip().lower(): s for s in existing}
    wanted = {label.lower() for label, _ in STAGES}
    spare = [s for s in existing if s["label"].strip().lower() not in wanted]
    touches_existing = False

    for order, (label, prob) in enumerate(STAGES):
        body = {"label": label, "displayOrder": order,
                "metadata": {"probability": str(prob)}}
        stage = by_label.get(label.lower())
        if stage:
            if stage.get("displayOrder") != order or _prob(stage) != prob:
                sid = stage["id"]
                plan.add(f"Update stage '{label}' (order {order}, probability {prob})",
                         lambda sid=sid, body=body: client.patch(
                             f"{PIPELINES}/{pid}/stages/{sid}", body))
        elif spare:
            old = spare.pop(0)
            touches_existing = True
            plan.add(f"Rename stage '{old['label']}' -> '{label}'",
                     lambda sid=old["id"], body=body: client.patch(
                         f"{PIPELINES}/{pid}/stages/{sid}", body))
        else:
            plan.add(f"Create stage '{label}'",
                     lambda body=body: client.post(f"{PIPELINES}/{pid}/stages", body))

    for old in spare:
        touches_existing = True
        # HubSpot blocks deleting a stage that holds deals, which is what we want.
        plan.add(f"Delete unused stage '{old['label']}' (only if empty)",
                 lambda sid=old["id"]: client.delete(f"{PIPELINES}/{pid}/stages/{sid}"))

    if touches_existing:
        found = client.post("/crm/v3/objects/deals/search", {
            "filterGroups": [{"filters": [
                {"propertyName": "pipeline", "operator": "EQ", "value": pid}]}],
            "limit": 1,
        })
        total = (found or {}).get("total", 0)
        if total:
            plan.blockers.append(
                f"The pipeline already holds {total} deal(s). Renaming or deleting "
                "its stages would move them. Archive or delete those deals in "
                "HubSpot first, then run this again.")


def plan_properties(client, plan: Plan, limit: int, skip_limit_check: bool) -> None:
    group = DEAL_PROPERTY_GROUP
    try:
        client.get(f"{PROPS}/deals/groups/{group['name']}")
        plan.notes.append(f"Property group '{group['label']}' already exists.")
    except HubSpotError as e:
        if not e.not_found:
            raise
        plan.add(f"Create deal property group '{group['label']}'",
                 lambda: client.post(f"{PROPS}/deals/groups", group))

    to_create = []
    for spec in DEAL_PROPERTIES:
        name = spec["name"]
        try:
            current = client.get(f"{PROPS}/deals/{name}")
        except HubSpotError as e:
            if not e.not_found:
                raise
            to_create.append(spec)
            plan.add(f"Create deal property '{spec['label']}' ({name}, {spec['fieldType']})",
                     lambda spec=spec: client.post(f"{PROPS}/deals", spec))
            continue

        if current.get("type") != spec["type"]:
            plan.blockers.append(
                f"Property '{name}' exists with type '{current.get('type')}', expected "
                f"'{spec['type']}'. HubSpot cannot change a property's type: delete it "
                "in Settings > Properties, then run this again.")
            continue
        changes = {}
        if current.get("label") != spec["label"]:
            changes["label"] = spec["label"]
        if current.get("groupName") != spec["groupName"]:
            changes["groupName"] = spec["groupName"]
        if "options" in spec:
            have = sorted(o.get("value") for o in current.get("options", []))
            if have != sorted(o["value"] for o in spec["options"]):
                changes["options"] = spec["options"]
        if changes:
            plan.add(f"Update deal property '{name}': {', '.join(changes)}",
                     lambda name=name, changes=changes: client.patch(
                         f"{PROPS}/deals/{name}", changes))

    # Free-plan limit: 10 custom properties in total across the account.
    counted = {obj: _custom_property_names(client, obj) for obj in COUNTED_OBJECTS}
    existing_total = sum(len(v) for v in counted.values())
    after = existing_total + len(to_create)
    detail = "; ".join(f"{obj}: {', '.join(v) or 'none'}" for obj, v in counted.items())
    plan.notes.append(f"Custom properties now: {existing_total} ({detail}). "
                      f"After setup: {after} of {limit} allowed.")
    if after > limit and not skip_limit_check:
        plan.blockers.append(
            f"Setup needs {len(to_create)} new custom properties but the account "
            f"already has {existing_total}, which would exceed the free-plan "
            f"limit of {limit}. Delete unused custom properties in Settings > "
            "Properties, or raise hubspot.custom_property_limit in config.yaml "
            "if your plan allows more.")

    try:
        client.get(f"{PROPS}/contacts/{CONTACT_LINKEDIN_PROPERTY}")
        plan.notes.append(f"Built-in contact property '{CONTACT_LINKEDIN_PROPERTY}' "
                          "(LinkedIn URL) found.")
    except HubSpotError as e:
        if not e.not_found:
            raise
        plan.notes.append(
            f"WARNING: contact property '{CONTACT_LINKEDIN_PROPERTY}' not found. "
            "Poster profile links will need another field (decided in M3).")


def build_plan(client, limit: int = 10, skip_limit_check: bool = False) -> Plan:
    plan = Plan()
    plan_pipeline(client, plan)
    plan_properties(client, plan, limit, skip_limit_check)
    return plan


def print_offline() -> None:
    print(f"Pipeline: {PIPELINE_LABEL}")
    for i, (label, prob) in enumerate(STAGES):
        print(f"  {i:>2}. {label:<18} probability {prob}")
    print(f"\nDeal property group: {DEAL_PROPERTY_GROUP['label']}")
    for p in DEAL_PROPERTIES:
        unique = " (unique)" if p.get("hasUniqueValue") else ""
        print(f"  - {p['label']:<20} {p['name']:<18} {p['fieldType']}{unique}")
    print(f"\nContact: built-in '{CONTACT_LINKEDIN_PROPERTY}' for poster LinkedIn URL")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="make the changes (default is a read-only plan)")
    parser.add_argument("--offline", action="store_true",
                        help="print the target model without calling HubSpot")
    parser.add_argument("--skip-limit-check", action="store_true",
                        help="ignore the custom property limit check")
    args = parser.parse_args(argv)

    if args.offline:
        print_offline()
        return 0

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    limit = int((config.get("hubspot") or {}).get("custom_property_limit", 10))

    load_dotenv(ROOT / ".env")
    client = HubSpotClient()
    plan = build_plan(client, limit, args.skip_limit_check)

    print("== HubSpot setup " + ("(APPLY)" if args.apply else "(PLAN ONLY, nothing will change)"))
    for note in plan.notes:
        print("  i ", note)
    if not plan.actions:
        print("  Everything is already set up. Nothing to do.")
    for desc, _ in plan.actions:
        print("  + ", desc)
    if plan.blockers:
        print("\nSTOPPED. Fix these first:")
        for b in plan.blockers:
            print("  ! ", b)
        return 1
    if not args.apply:
        if plan.actions:
            print("\nPlan only. Run again with --apply to make these changes.")
        return 0

    failures = 0
    for desc, fn in plan.actions:
        try:
            fn()
            print("  done:", desc)
        except HubSpotError as e:
            failures += 1
            print("  FAILED:", desc, "->", e)
    if failures:
        print(f"\n{failures} change(s) failed. Fix the cause and re-run (safe to repeat).")
        return 1
    print("\nHubSpot setup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
