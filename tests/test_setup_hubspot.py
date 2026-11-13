"""Tests for scripts/setup_hubspot.py against an in-memory fake HubSpot."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from src.hubspot_client import HubSpotError
from src.hubspot_schema import DEAL_PROPERTIES, PIPELINE_LABEL, STAGES

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("setup_hubspot", ROOT / "scripts" / "setup_hubspot.py")
setup = importlib.util.module_from_spec(spec)
sys.modules["setup_hubspot"] = setup
spec.loader.exec_module(setup)

DEFAULT_STAGES = ["Appointment scheduled", "Qualified to buy", "Presentation scheduled",
                  "Decision maker bought-in", "Contract sent", "Closed won", "Closed lost"]


class FakeHubSpot:
    """Behaves like a fresh free HubSpot account for the endpoints we use."""

    def __init__(self, deals_in_pipeline=0, extra_custom=()):
        self.pipeline = {
            "id": "default", "label": "Sales Pipeline",
            "stages": [{"id": f"s{i}", "label": label, "displayOrder": i,
                        "metadata": {"probability": "0.5"}}
                       for i, label in enumerate(DEFAULT_STAGES)],
        }
        self.props = {
            "deals": {"dealname": {"name": "dealname", "type": "string", "hubspotDefined": True}},
            "contacts": {"hs_linkedin_url": {"name": "hs_linkedin_url", "type": "string",
                                             "hubspotDefined": True}},
            "companies": {},
        }
        for name in extra_custom:
            self.props["contacts"][name] = {"name": name, "type": "string"}
        self.groups = set()
        self.deals_in_pipeline = deals_in_pipeline
        self.writes = []
        self._next = 100

    def _404(self, path):
        raise HubSpotError(404, "not found", "OBJECT_NOT_FOUND", path)

    def get(self, path, params=None):
        parts = path.strip("/").split("/")
        if path == "/crm/v3/pipelines/deals":
            return {"results": [copy.deepcopy(self.pipeline)]}
        if parts[:3] == ["crm", "v3", "properties"]:
            obj = parts[3]
            if len(parts) == 4:
                return {"results": list(self.props[obj].values())}
            if parts[4] == "groups":
                if parts[5] in self.groups:
                    return {"name": parts[5]}
                self._404(path)
            if parts[4] in self.props[obj]:
                return copy.deepcopy(self.props[obj][parts[4]])
            self._404(path)
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, json):
        self.writes.append(("POST", path)) if "search" not in path else None
        if path == "/crm/v3/objects/deals/search":
            return {"total": self.deals_in_pipeline, "results": []}
        if path.endswith("/stages"):
            self._next += 1
            self.pipeline["stages"].append({"id": f"s{self._next}", **copy.deepcopy(json)})
            return {}
        if path == "/crm/v3/properties/deals/groups":
            self.groups.add(json["name"])
            return {}
        if path == "/crm/v3/properties/deals":
            self.props["deals"][json["name"]] = copy.deepcopy(json)
            return {}
        raise AssertionError(f"unexpected POST {path}")

    def patch(self, path, json):
        self.writes.append(("PATCH", path))
        if path == "/crm/v3/pipelines/deals/default":
            self.pipeline.update(json)
            return {}
        if "/stages/" in path:
            sid = path.rsplit("/", 1)[1]
            stage = next(s for s in self.pipeline["stages"] if s["id"] == sid)
            stage.update(copy.deepcopy(json))
            return {}
        if path.startswith("/crm/v3/properties/deals/"):
            self.props["deals"][path.rsplit("/", 1)[1]].update(copy.deepcopy(json))
            return {}
        raise AssertionError(f"unexpected PATCH {path}")

    def delete(self, path, params=None):
        self.writes.append(("DELETE", path))
        sid = path.rsplit("/", 1)[1]
        self.pipeline["stages"] = [s for s in self.pipeline["stages"] if s["id"] != sid]


def apply(plan):
    assert not plan.blockers, plan.blockers
    for _, fn in plan.actions:
        fn()


def test_plan_makes_no_writes():
    hs = FakeHubSpot()
    plan = setup.build_plan(hs)
    assert plan.actions and not plan.blockers
    assert hs.writes == []


def test_apply_builds_the_prd_model():
    hs = FakeHubSpot()
    apply(setup.build_plan(hs))

    assert hs.pipeline["label"] == PIPELINE_LABEL
    stages = sorted(hs.pipeline["stages"], key=lambda s: s["displayOrder"])
    assert [s["label"] for s in stages] == [label for label, _ in STAGES]
    assert [float(s["metadata"]["probability"]) for s in stages] == [p for _, p in STAGES]
    # default stages were reused (renamed), not left behind
    assert {"s0", "s6"} <= {s["id"] for s in stages}

    assert "gtm_job_engine" in hs.groups
    for p in DEAL_PROPERTIES:
        assert hs.props["deals"][p["name"]]["type"] == p["type"]
    assert hs.props["deals"]["job_url"]["hasUniqueValue"] is True


def test_rerun_is_safe_and_changes_nothing():
    hs = FakeHubSpot()
    apply(setup.build_plan(hs))
    hs.writes.clear()
    plan = setup.build_plan(hs)
    assert plan.actions == []
    assert plan.blockers == []
    assert hs.writes == []


def test_stops_before_exceeding_custom_property_limit():
    hs = FakeHubSpot(extra_custom=["old_field_1", "old_field_2"])  # 2 + 9 = 11 > 10
    plan = setup.build_plan(hs, limit=10)
    assert any("limit" in b for b in plan.blockers)


def test_limit_counts_properties_already_created_by_us():
    hs = FakeHubSpot()
    apply(setup.build_plan(hs))
    plan = setup.build_plan(hs, limit=10)  # 9 existing + 0 new = fine
    assert not plan.blockers


def test_stops_if_pipeline_already_has_deals():
    hs = FakeHubSpot(deals_in_pipeline=3)
    plan = setup.build_plan(hs)
    assert any("3 deal" in b for b in plan.blockers)


def test_wrong_property_type_is_a_blocker():
    hs = FakeHubSpot()
    hs.props["deals"]["fit_score"] = {"name": "fit_score", "type": "string", "label": "Fit Score"}
    plan = setup.build_plan(hs)
    assert any("fit_score" in b for b in plan.blockers)


def test_offline_mode_needs_no_token(capsys, monkeypatch):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    assert setup.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "Job Applications" in out and "job_url" in out


def test_missing_token_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.setattr(setup, "load_dotenv", lambda path: None)
    with pytest.raises(SystemExit) as exc:
        setup.main([])
    assert "HUBSPOT_TOKEN" in str(exc.value)


def test_free_plan_fits_in_ten_custom_properties():
    assert len(DEAL_PROPERTIES) <= 9  # keep one spare slot
