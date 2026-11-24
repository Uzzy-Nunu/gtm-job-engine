"""Intake: turn one captured or imported job into one HubSpot deal (PRD §10.1).

Flow for each submission:
  1. Work out the duplicate key: the canonical LinkedIn post URL, or the
     normalised job URL (IN-1c, IN-4). LinkedIn is never contacted.
  2. If a deal with that key exists, don't create another. If that deal was
     waiting for post text and text has now arrived, add it (IN-1f).
  3. Cross-source duplicates (same "Title - Company" within 14 days) are
     skipped with a reason (IN-4).
  4. Find or create the company (IN-5) and the poster contact (IN-6).
  5. Create the deal in "New", link it to the company and contact, and flag
     "NEEDS POST TEXT" when a LinkedIn link arrives with no text and no
     external job link (IN-1f).

Safe to re-run: the same submission twice never makes two deals (OP-4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.hubspot_client import HubSpotError
from src.hubspot_schema import (CONTACT_LINKEDIN_PROPERTY, NEEDS_POST_TEXT,
                                PIPELINE_LABEL)
from src.urls import (URLError, company_domain, find_external_job_links,
                      is_linkedin, linkedin_job_url, normalise_url, parse_linkedin_post)

MAX_TEXT = 60_000  # HubSpot multi-line text limit is 65,536 characters
NOTES_MARKER = "\n\n--- Notes from Peace ---"
SAME_TEXT_THRESHOLD = 0.6  # share of words in common

# LinkedIn gives one post two different IDs (the address bar shows an
# "activity" ID, "Copy link to post" often a "ugcPost" ID), so the URL alone
# can't always spot a repeat. A recent capture from the same poster counts as
# the same post when either side has no text yet, or the texts mostly match.


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", (text or "").lower()))


def similar_text(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    if not x or not y:
        return 0.0
    return len(x & y) / min(len(x), len(y))


def _post_text(description: str | None) -> str:
    return (description or "").split(NOTES_MARKER)[0].strip()


def ms(dt: datetime) -> str:
    """HubSpot search compares dates as milliseconds since 1970."""
    return str(int(dt.timestamp() * 1000))

ATS_SOURCES = {"greenhouse.io": "Greenhouse", "lever.co": "Lever", "ashbyhq.com": "Ashby",
               "remoteok.com": "RemoteOK", "himalayas.app": "Himalayas",
               "weworkremotely.com": "WWR", "remotive.com": "Remotive", "jobicy.com": "Jobicy"}


@dataclass
class Submission:
    url: str
    text: str = ""
    notes: str = ""
    source: str | None = None        # one of hubspot_schema.JOB_SOURCES
    title: str | None = None         # known for job-board imports
    company: str | None = None
    company_website: str | None = None
    apply_url: str | None = None
    needs_text: bool = False         # created without a description: flag NEEDS POST TEXT


@dataclass
class Result:
    status: str                      # created | duplicate | updated | error
    message: str
    deal_id: str | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status != "error"


def _source_for(url: str) -> str:
    host = url.split("/")[2] if "//" in url else url
    for domain, source in ATS_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            return source
    return "Company Site"


def _split_name(name: str) -> tuple[str, str]:
    first, _, rest = name.partition(" ")
    return first, (rest + " (unconfirmed)").strip()


class Intake:
    def __init__(self, hubspot, duplicate_window_days: int = 14, now=None):
        self.hs = hubspot
        self.window = timedelta(days=duplicate_window_days)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._pipeline_id = None
        self._new_stage_id = None

    # --- public ---------------------------------------------------------
    def submit(self, sub: Submission) -> Result:
        try:
            return self._submit(sub)
        except URLError as e:
            return Result("error", str(e))
        except HubSpotError as e:
            return Result("error", f"HubSpot error: {e}")

    # --- steps ----------------------------------------------------------
    def _resolve_pipeline(self):
        if self._pipeline_id:
            return
        for p in self.hs.get("/crm/v3/pipelines/deals").get("results", []):
            if p.get("label") == PIPELINE_LABEL:
                new = next((s for s in p["stages"] if s["label"] == "New"), None)
                if new:
                    self._pipeline_id, self._new_stage_id = p["id"], new["id"]
                    return
        raise HubSpotError(404, f"Pipeline '{PIPELINE_LABEL}' with a 'New' stage not found. "
                                "Run Setup HubSpot first.", "SETUP", "pipelines")

    def _search_one(self, obj, filters, properties=None):
        body = {"filterGroups": [{"filters": filters}], "limit": 1}
        if properties:
            body["properties"] = properties
        found = self.hs.post(f"/crm/v3/objects/{obj}/search", body)
        results = (found or {}).get("results", [])
        return results[0] if results else None

    def _submit(self, sub: Submission) -> Result:
        self._resolve_pipeline()
        text = (sub.text or "").strip()[:MAX_TEXT]
        notes = (sub.notes or "").strip()

        post = parse_linkedin_post(sub.url) if is_linkedin(sub.url) and not linkedin_job_url(sub.url) else None
        key = post.canonical_url if post else normalise_url(sub.url)
        source = sub.source or ("LinkedIn Post" if post else _source_for(key))

        # 1-2. Exact duplicate on the unique key
        existing = self._search_one("deals", [{"propertyName": "job_url", "operator": "EQ", "value": key}],
                                    ["dealname", "pipeline_error", "description"])
        if existing:
            # A job still waiting for its description only counts as updated by real text.
            return self._handle_existing(existing, "" if sub.needs_text else text, notes)
        if post and post.profile_url:
            twin = self._same_poster_twin(post, text)
            if twin:
                return self._handle_existing(
                    twin, text, notes,
                    "Looks like the same post as a recent capture from this poster "
                    "(LinkedIn gives one post two different links).")

        # 3. Cross-source duplicate (same title + company, recent)
        deal_name = self._deal_name(sub, post, key)
        if sub.title and sub.company:
            twin = self._search_one("deals", [
                {"propertyName": "dealname", "operator": "EQ", "value": deal_name},
                {"propertyName": "createdate", "operator": "GTE", "value": ms(self._now() - self.window)},
            ], ["dealname"])
            if twin:
                return Result("duplicate", f"Same role already captured from another source "
                                           f"in the last {self.window.days} days.", twin["id"])

        # 4. Company and poster
        external = find_external_job_links(text)
        apply_url = sub.apply_url and normalise_url(sub.apply_url)
        apply_url = apply_url or (external[0] if external else (None if post else key))
        company_id = self._upsert_company(sub, apply_url)
        contact_id = self._upsert_poster(post) if post and post.profile_url else None

        # 5. Deal
        flags = []
        pipeline_error = None
        if post and not text and not external:
            flags.append(NEEDS_POST_TEXT)
            pipeline_error = (f"{NEEDS_POST_TEXT}: open this deal in HubSpot and paste the "
                              "LinkedIn post text into 'Deal description'.")
        if sub.needs_text and not pipeline_error:
            flags.append(NEEDS_POST_TEXT)
            pipeline_error = (f"{NEEDS_POST_TEXT}: open the LinkedIn job (Apply URL), copy the job description "
                              "and paste it into 'Deal description', then clear this field.")
        if post and post.name_guess:
            flags.append("POSTER NAME UNCONFIRMED")

        description = text
        if notes:
            description = f"{text}{NOTES_MARKER}\n{notes}".strip()

        props = {
            "dealname": deal_name,
            "pipeline": self._pipeline_id,
            "dealstage": self._new_stage_id,
            "job_url": key,
            "job_source": source,
        }
        if apply_url:
            props["apply_url"] = apply_url
        if description:
            props["description"] = description[:MAX_TEXT]
        if pipeline_error:
            props["pipeline_error"] = pipeline_error

        try:
            deal = self.hs.post("/crm/v3/objects/deals", {"properties": props})
        except HubSpotError as e:
            if e.status == 409:  # created by a parallel run between search and create
                return Result("duplicate", "Already captured (found while saving).")
            raise
        deal_id = deal["id"]
        if company_id:
            self._associate("deals", deal_id, "companies", company_id)
        if contact_id:
            self._associate("deals", deal_id, "contacts", contact_id)
            if company_id:
                self._associate("contacts", contact_id, "companies", company_id)

        msg = "Saved to HubSpot as a new job."
        if NEEDS_POST_TEXT in flags:
            msg += " No post text yet: paste it into the deal's description when you can."
        return Result("created", msg, deal_id, flags)

    def _handle_existing(self, deal, text, notes, lead: str = "Already captured.") -> Result:
        props = deal.get("properties", {})
        waiting = (props.get("pipeline_error") or "").startswith(NEEDS_POST_TEXT)
        if waiting and text:
            description = f"{text}{NOTES_MARKER}\n{notes}" if notes else text
            self.hs.patch(f"/crm/v3/objects/deals/{deal['id']}", {"properties": {
                "description": description[:MAX_TEXT], "pipeline_error": ""}})
            return Result("updated", f"{lead} Added the post text you sent.", deal["id"])
        message = f"{lead} No new deal created."
        if not text and not lead.startswith("Already"):
            message += " If this is a different post, paste its text and save again."
        return Result("duplicate", message, deal["id"])

    def _same_poster_twin(self, post, text):
        contact = self._search_one("contacts", [{"propertyName": CONTACT_LINKEDIN_PROPERTY,
                                                 "operator": "EQ", "value": post.profile_url}])
        if not contact:
            return None
        found = self.hs.post("/crm/v3/objects/deals/search", {
            "filterGroups": [{"filters": [
                {"propertyName": "associations.contact", "operator": "EQ", "value": contact["id"]},
                {"propertyName": "job_source", "operator": "EQ", "value": "LinkedIn Post"},
                {"propertyName": "createdate", "operator": "GTE", "value": ms(self._now() - self.window)},
            ]}],
            "properties": ["dealname", "pipeline_error", "description"],
            "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
            "limit": 10,
        })
        for deal in (found or {}).get("results", []):
            earlier = _post_text(deal.get("properties", {}).get("description"))
            if not text or not earlier or similar_text(earlier, text) >= SAME_TEXT_THRESHOLD:
                return deal
        return None

    def _deal_name(self, sub, post, key) -> str:
        if sub.title and sub.company:
            return f"{sub.title.strip()} - {sub.company.strip()}"
        if sub.title:  # company is filled in later by the Qualify step
            return f"{sub.title.strip()} - company TBC"
        if post:
            who = post.name_guess or "unknown poster"
            return f"LinkedIn post by {who} ({post.post_id[-6:]})"
        host = key.split("/")[2]
        return f"Job at {company_domain(key) or host}"

    def _upsert_company(self, sub, apply_url) -> str | None:
        domain = None
        for candidate in (sub.company_website, apply_url):
            if candidate:
                try:
                    domain = company_domain(candidate)
                except URLError:
                    domain = None
                if domain:
                    break
        name = (sub.company or "").strip() or None
        if not domain and not name:
            return None
        if domain:
            found = self._search_one("companies", [{"propertyName": "domain", "operator": "EQ", "value": domain}])
            if found:
                return found["id"]
        if name:
            found = self._search_one("companies", [{"propertyName": "name", "operator": "EQ", "value": name}])
            if found:
                return found["id"]
        props = {"name": name or domain}
        if domain:
            props["domain"] = domain
        return self.hs.post("/crm/v3/objects/companies", {"properties": props})["id"]

    def _upsert_poster(self, post) -> str:
        found = self._search_one("contacts", [{"propertyName": CONTACT_LINKEDIN_PROPERTY,
                                               "operator": "EQ", "value": post.profile_url}])
        if found:
            return found["id"]
        props = {CONTACT_LINKEDIN_PROPERTY: post.profile_url}
        if post.name_guess:
            props["firstname"], props["lastname"] = _split_name(post.name_guess)
        return self.hs.post("/crm/v3/objects/contacts", {"properties": props})["id"]

    def _associate(self, from_obj, from_id, to_obj, to_id):
        self.hs.put(f"/crm/v4/objects/{from_obj}/{from_id}/associations/default/{to_obj}/{to_id}")
