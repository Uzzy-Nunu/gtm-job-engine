"""Generic reader for any job board that publishes an RSS or Atom feed.

Add a board in config.yaml under `extra_feeds:` (name + url). No code needed:

  extra_feeds:
    - name: Example Remote Jobs
      url: https://jobs.example/remote.rss
      title_format: auto        # optional: auto | "company: role" | "role at company" | role
      company: Example Inc      # optional: for one company's own feed
      link_from: guid           # optional: use the item's permanent ID as the job link
                                # (when the feed mixes link styles for the same job)

Feeds are read politely (one request each) and every job still passes the
same title, location and date filters as the built-in boards.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from src.sources.base import Http, JobPosting, from_iso, html_to_text

LOCATION_TAGS = ("region", "location", "job_location", "country")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node, *names) -> str:
    for child in node:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text.strip()
    return ""


def _link(node) -> str:
    for child in node:
        if _local(child.tag) == "link":
            href = child.get("href")
            if href and child.get("rel", "alternate") == "alternate":
                return href.strip()
            if (child.text or "").strip():
                return child.text.strip()
    return _child_text(node, "guid", "id")


def _date(node):
    raw = _child_text(node, "pubdate", "published", "updated", "date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return from_iso(raw)


def split_title(title: str, fmt: str = "auto") -> tuple[str, str]:
    """Return (role, company) from a feed item title."""
    title = re.sub(r"\s+", " ", title or "").strip()
    fmt = (fmt or "auto").lower()
    if fmt in ("auto", "role at company"):
        m = re.match(r"^(?P<role>.+?) at (?P<company>[^()\[\]]+?)(?: \(.*\))?$", title)
        if m:
            return m.group("role").strip(), m.group("company").strip()
    if fmt in ("auto", "company: role"):
        company, sep, role = title.partition(": ")
        if sep and len(company) <= 60:
            return role.strip(), company.strip()
    return title, ""


def read_feed(http: Http, feed: dict) -> list[JobPosting]:
    name = feed.get("name") or feed["url"]
    root = ET.fromstring(http.text(feed["url"]).encode("utf-8"))
    items = [n for n in root.iter() if _local(n.tag) in ("item", "entry")]
    jobs = []
    for item in items:
        role, company = split_title(_child_text(item, "title"), feed.get("title_format", "auto"))
        body = _child_text(item, "description", "summary", "content", "encoded")
        url = _child_text(item, "guid", "id") if feed.get("link_from") == "guid" else ""
        jobs.append(JobPosting(
            source="Other",
            url=url or _link(item),
            title=role,
            company=feed.get("company") or company,
            text=f"Board: {name}\n\n" + html_to_text(body),
            location=_child_text(item, *LOCATION_TAGS),
            posted_at=_date(item),
        ))
    return jobs
