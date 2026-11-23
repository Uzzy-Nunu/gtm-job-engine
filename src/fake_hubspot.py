"""An in-memory stand-in for HubSpot, used by dry-run mode and tests (PRD OP-1).

It implements only the endpoints the pipeline uses, with the same request
and response shapes as the real API, so code can't tell the difference.
Nothing is sent anywhere.
"""

from __future__ import annotations

import copy
import itertools
from datetime import datetime, timezone

from src.hubspot_client import HubSpotError
from src.hubspot_schema import PIPELINE_LABEL, STAGES

UNIQUE_PROPERTIES = {"deals": {"job_url"}}
OBJECTS = ("deals", "contacts", "companies", "notes")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _sortable(value):
    """Numbers sort as numbers ("100" after "56"); dates and text sort as text."""
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value or ""))


def _as_datetime(value):
    if value is None:
        return None
    text = str(value)
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class FakeHubSpot:
    def __init__(self):
        self._ids = itertools.count(1001)
        self.objects: dict[str, dict[str, dict]] = {o: {} for o in OBJECTS}
        self.associations: set[tuple[str, str, str, str]] = set()
        self.pipeline = {
            "id": "default", "label": PIPELINE_LABEL,
            "stages": [{"id": f"stage{i}", "label": label, "displayOrder": i,
                        "metadata": {"probability": str(p)}}
                       for i, (label, p) in enumerate(STAGES)],
        }
        self.calls: list[tuple[str, str]] = []
        self.files: dict[str, dict] = {}

    # --- helpers for tests and dry-run reports -------------------------
    def all(self, obj: str) -> list[dict]:
        return list(self.objects[obj].values())

    def associated(self, from_obj, from_id, to_obj) -> list[str]:
        return sorted(t_id for f, f_id, t, t_id in self.associations
                      if f == from_obj and f_id == str(from_id) and t == to_obj)

    def stage_label(self, stage_id: str) -> str:
        return next(s["label"] for s in self.pipeline["stages"] if s["id"] == stage_id)

    # --- HTTP-style interface (same as HubSpotClient) -------------------
    def get(self, path, params=None):
        self.calls.append(("GET", path))
        if path == "/crm/v3/pipelines/deals":
            return {"results": [copy.deepcopy(self.pipeline)]}
        if path == "/account-info/v3/details":
            return {"portalId": 123456, "uiDomain": "app.hubspot.com", "timeZone": "Africa/Lagos"}
        parts = path.strip("/").split("/")
        if parts[:3] == ["crm", "v4", "objects"] and len(parts) == 7 and parts[5] == "associations":
            # GET /crm/v4/objects/{from}/{id}/associations/{to}
            return {"results": [{"toObjectId": int(i)} for i in self.associated(parts[3], parts[4], parts[6])]}
        if parts[:3] == ["crm", "v3", "objects"] and len(parts) == 5:
            record = self.objects[parts[3]].get(parts[4])
            if not record:
                raise HubSpotError(404, "Object not found", "OBJECT_NOT_FOUND", path)
            return copy.deepcopy(record)
        raise HubSpotError(404, f"FakeHubSpot has no GET {path}", "NOT_IMPLEMENTED", path)

    def post(self, path, json):
        self.calls.append(("POST", path))
        parts = path.strip("/").split("/")
        if parts[:3] == ["crm", "v3", "objects"]:
            obj = parts[3]
            if len(parts) == 5 and parts[4] == "search":
                return self._search(obj, json)
            if len(parts) == 4:
                record = self._create(obj, json.get("properties", {}), path)
                for assoc in json.get("associations", []):
                    to_id = str(assoc["to"]["id"])
                    to_obj = next((o for o in OBJECTS if to_id in self.objects[o] and o != obj), None)
                    if to_obj:
                        self.associations.add((obj, record["id"], to_obj, to_id))
                        self.associations.add((to_obj, to_id, obj, record["id"]))
                return record
        raise HubSpotError(404, f"FakeHubSpot has no POST {path}", "NOT_IMPLEMENTED", path)

    def patch(self, path, json):
        self.calls.append(("PATCH", path))
        parts = path.strip("/").split("/")
        if parts[:3] == ["crm", "v3", "objects"] and len(parts) == 5:
            record = self.objects[parts[3]].get(parts[4])
            if not record:
                raise HubSpotError(404, "Object not found", "OBJECT_NOT_FOUND", path)
            self._check_unique(parts[3], json.get("properties", {}), path, exclude=parts[4])
            record["properties"].update({k: (None if v is None else str(v))
                                         for k, v in json.get("properties", {}).items()})
            record["properties"]["hs_lastmodifieddate"] = _now_iso()
            return copy.deepcopy(record)
        raise HubSpotError(404, f"FakeHubSpot has no PATCH {path}", "NOT_IMPLEMENTED", path)

    def put(self, path, json=None):
        self.calls.append(("PUT", path))
        # /crm/v4/objects/{from}/{id}/associations/default/{to}/{toId}
        parts = path.strip("/").split("/")
        if parts[:3] == ["crm", "v4", "objects"] and parts[5:7] == ["associations", "default"]:
            f, f_id, t, t_id = parts[3], parts[4], parts[7], parts[8]
            for obj, oid in ((f, f_id), (t, t_id)):
                if oid not in self.objects[obj]:
                    raise HubSpotError(404, "Object not found", "OBJECT_NOT_FOUND", path)
            self.associations.add((f, f_id, t, t_id))
            self.associations.add((t, t_id, f, f_id))
            return {"status": "COMPLETE"}
        raise HubSpotError(404, f"FakeHubSpot has no PUT {path}", "NOT_IMPLEMENTED", path)

    def upload(self, filename: str, content: bytes, folder_path: str, access: str = "PRIVATE") -> dict:
        self.calls.append(("UPLOAD", folder_path))
        fid = str(next(self._ids))
        self.files[fid] = {"id": fid, "name": filename, "path": f"{folder_path}/{filename}",
                           "access": access, "size": len(content), "url": f"https://files.example/{fid}"}
        return copy.deepcopy(self.files[fid])

    def delete(self, path, params=None):
        self.calls.append(("DELETE", path))
        raise HubSpotError(404, f"FakeHubSpot has no DELETE {path}", "NOT_IMPLEMENTED", path)

    # --- internals ------------------------------------------------------
    def _check_unique(self, obj, props, path, exclude=None):
        for name in UNIQUE_PROPERTIES.get(obj, ()):
            value = props.get(name)
            if not value:
                continue
            for oid, rec in self.objects[obj].items():
                if oid != exclude and rec["properties"].get(name) == value:
                    raise HubSpotError(409, f"A {obj[:-1]} with {name}={value} already exists",
                                       "CONFLICT", path)

    def _create(self, obj, props, path):
        self._check_unique(obj, props, path)
        oid = str(next(self._ids))
        now = _now_iso()
        record = {"id": oid, "properties": {k: (None if v is None else str(v)) for k, v in props.items()}}
        record["properties"].update({"hs_object_id": oid, "createdate": now, "hs_lastmodifieddate": now})
        self.objects[obj][oid] = record
        return copy.deepcopy(record)

    def _matches(self, record, flt, obj=None) -> bool:
        name = flt["propertyName"]
        if name.startswith("associations."):  # e.g. deals linked to a contact
            other = name.split(".", 1)[1] + "s"
            return (obj, record["id"], other, str(flt.get("value"))) in self.associations
        value = record["properties"].get(name)
        op = flt["operator"]
        target = flt.get("value")
        if op == "EQ":
            return value is not None and str(value).lower() == str(target).lower()
        if op == "NEQ":
            return value is None or str(value).lower() != str(target).lower()
        if op == "HAS_PROPERTY":
            return value not in (None, "")
        if op == "NOT_HAS_PROPERTY":
            return value in (None, "")
        if op == "CONTAINS_TOKEN":
            return value is not None and str(target).strip("*").lower() in str(value).lower()
        if op in ("GTE", "LTE", "GT", "LT"):
            if value is None:
                return False
            left, right = _as_datetime(value), _as_datetime(target)
            return {"GTE": left >= right, "LTE": left <= right,
                    "GT": left > right, "LT": left < right}[op]
        if op == "IN":
            return value is not None and str(value).lower() in [str(v).lower() for v in flt.get("values", [])]
        raise HubSpotError(400, f"FakeHubSpot doesn't support operator {op}", "VALIDATION_ERROR", "search")

    def _search(self, obj, body):
        groups = body.get("filterGroups") or [{"filters": []}]
        hits = [rec for rec in self.objects[obj].values()
                if any(all(self._matches(rec, f, obj) for f in g.get("filters", [])) for g in groups)]
        for sort in reversed(body.get("sorts", [])):
            key = sort.get("propertyName")
            hits.sort(key=lambda r: (r["properties"].get(key) is None, _sortable(r["properties"].get(key))),
                      reverse=sort.get("direction") == "DESCENDING")
        limit = int(body.get("limit", 10))
        props = body.get("properties")
        results = []
        for rec in hits[:limit]:
            rec = copy.deepcopy(rec)
            if props:
                rec["properties"] = {k: v for k, v in rec["properties"].items()
                                     if k in props or k == "hs_object_id"}
            results.append(rec)
        return {"total": len(hits), "results": results}
