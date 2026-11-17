"""Cheap pre-filters applied to job-board results before anything reaches
HubSpot or the AI (PRD §10.1 IN-3, §10.2 QU-2).

These only remove clear non-matches. The real fit judgement happens in the
Qualify step (M4).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

REMOTE_WORDS = ("remote", "anywhere", "worldwide", "global", "distributed",
                "work from home", "wfh")
ONSITE_ONLY = ("on-site", "onsite", "in office", "in-office", "hybrid")


def _norm(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[-_/|,()\[\]:.+]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    phrase = _norm(phrase)
    return bool(phrase) and re.search(rf"(^| ){re.escape(phrase)}($| )", haystack) is not None


class TitleFilter:
    def __init__(self, target: list[str], adjacent: list[str], excluded: list[str],
                 explore: list[str] | None = None):
        self.target = target
        self.adjacent = adjacent
        self.excluded = excluded
        self.explore = explore or []

    @classmethod
    def from_config(cls, config: dict) -> "TitleFilter":
        return cls(config.get("target_titles") or [], config.get("adjacent_titles") or [],
                   config.get("excluded_title_words") or [], config.get("explore_titles") or [])

    def match(self, title: str) -> str | None:
        """'target', 'adjacent', 'explore', or None when the title should be skipped."""
        t = _norm(title)
        if any(_contains_phrase(t, word) for word in self.excluded):
            return None
        if any(_contains_phrase(t, p) for p in self.target):
            return "target"
        if any(_contains_phrase(t, p) for p in self.adjacent):
            return "adjacent"
        if any(_contains_phrase(t, p) for p in self.explore):
            return "explore"
        return None


def looks_remote(location: str | None, workplace_type: str | None = None) -> bool:
    """For company job boards, which mix office and remote roles. Unknown or
    blank locations are kept so the Qualify step can decide."""
    wt = (workplace_type or "").lower().replace("_", "-")
    if wt in ("remote",):
        return True
    if wt in ("on-site", "onsite", "hybrid", "in-office"):
        return False
    loc = (location or "").lower()
    if not loc.strip():
        return True
    if any(w in loc for w in REMOTE_WORDS):
        return True
    return False


OPEN_WORDS = ("anywhere", "worldwide", "global", "international")
FALSE_FRIENDS = ("south africa", "central african republic")


def region_ok(location: str | None, eligible: list[str]) -> bool:
    """False only when the location clearly limits the role to places Peace
    isn't eligible for (e.g. 'USA Only', 'Remote - US', 'London').
    Blank, plain 'Remote' and anything naming an eligible region pass."""
    loc = _norm(location or "")
    if not loc:
        return True
    # Country names that contain a region word ("South Africa" is not "Africa").
    for country in FALSE_FRIENDS:
        loc = re.sub(rf"(^| ){re.escape(country)}($| )", " ", loc)
    loc = re.sub(r"\s+", " ", loc).strip()
    if not loc:
        return False  # only a country that merely looks like a region
    if any(_contains_phrase(loc, w) for w in OPEN_WORDS):
        return True
    if any(_contains_phrase(loc, region) for region in eligible):
        return True
    leftover = re.sub(r"\b(remote|fully|100%?|only|work|from|home|wfh|ok|job|position)\b", " ", loc)
    return not leftover.strip()


def is_recent(posted_at: datetime | None, max_age_days: int, now: datetime | None = None) -> bool:
    if posted_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return now - posted_at <= timedelta(days=max_age_days)
