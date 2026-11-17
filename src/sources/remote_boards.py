"""Readers for remote-only job boards: RemoteOK, Himalayas, We Work Remotely.

RemoteOK's API terms ask users to credit RemoteOK as the source and link
back. Each deal keeps the RemoteOK listing as its Job URL and "RemoteOK" as
its Job Source.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from src.sources.base import (Http, JobPosting, from_epoch, from_iso,
                              html_to_text, salary_text)


def remoteok(http: Http) -> list[JobPosting]:
    data = http.json("https://remoteok.com/api")
    jobs = []
    for j in data if isinstance(data, list) else []:
        if not isinstance(j, dict) or "position" not in j:
            continue  # first element is the legal notice
        jobs.append(JobPosting(
            source="RemoteOK",
            url=j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug') or j.get('id')}",
            title=(j.get("position") or "").strip(),
            company=(j.get("company") or "").strip(),
            text=html_to_text(j.get("description")),
            location=j.get("location") or "",
            workplace_type="remote",
            apply_url=j.get("apply_url") or None,
            posted_at=from_epoch(j.get("epoch")) or from_iso(j.get("date")),
            salary=salary_text(j.get("salary_min"), j.get("salary_max")),
        ))
    return jobs


def himalayas(http: Http, queries: list[str], pages: int = 2, page_size: int = 20) -> list[JobPosting]:
    """Searches Himalayas once per query (your target and adjacent titles)."""
    jobs = []
    for query in queries:
        jobs.extend(_himalayas_search(http, query, pages, page_size))
    return jobs


def _himalayas_search(http: Http, query: str, pages: int, page_size: int) -> list[JobPosting]:
    jobs = []
    for page in range(pages):
        data = http.json("https://himalayas.app/jobs/api/search",
                         params={"q": query, "limit": page_size, "offset": page * page_size})
        batch = data.get("jobs", [])
        for j in batch:
            restrictions = j.get("locationRestrictions") or []
            jobs.append(JobPosting(
                source="Himalayas",
                url=j.get("guid") or j.get("applicationLink") or "",
                title=(j.get("title") or "").strip(),
                company=(j.get("companyName") or "").strip(),
                text=html_to_text(j.get("description")) or (j.get("excerpt") or ""),
                location=", ".join(restrictions) if restrictions else "Worldwide",
                workplace_type="remote",
                apply_url=j.get("applicationLink") or None,
                posted_at=from_epoch(j.get("pubDate")),
                salary=salary_text(j.get("minSalary"), j.get("maxSalary"),
                                   j.get("currency"), j.get("salaryPeriod")),
            ))
        if len(batch) < page_size:
            break
    return jobs


def remotive(http: Http) -> list[JobPosting]:
    """https://github.com/remotive-com/remote-jobs-api
    Terms: max ~4 requests a day (we make one per run), link back to the
    Remotive listing and name Remotive as the source, never re-post the jobs
    on other job sites. Jobs appear with a 24-hour delay."""
    data = http.json("https://remotive.com/api/remote-jobs")
    jobs = []
    for j in data.get("jobs", []):
        jobs.append(JobPosting(
            source="Remotive",
            url=j.get("url") or "",
            title=(j.get("title") or "").strip(),
            company=(j.get("company_name") or "").strip(),
            text=html_to_text(j.get("description")),
            location=j.get("candidate_required_location") or "",
            workplace_type="remote",
            posted_at=from_iso(j.get("publication_date")),
            salary=j.get("salary") or None,
        ))
    return jobs


def jobicy(http: Http, geos: list[str], max_pages: int = 3) -> list[JobPosting]:
    """https://jobicy.com/jobs-rss-feed (public API, no key)
    Terms: at most one automated pass per hour, credit Jobicy as the source.
    Returns jobs from the last 7 days."""
    jobs = []
    for geo in geos:
        cursor = None
        for _ in range(max_pages):
            params = {"count": 100, "geo": geo}
            if cursor:
                params["cursor"] = cursor
            data = http.json("https://jobicy.com/api/jobs", params=params)
            for j in data.get("jobs", []):
                jobs.append(JobPosting(
                    source="Jobicy",
                    url=j.get("url") or "",
                    title=html_to_text(j.get("jobTitle") or ""),
                    company=(j.get("companyName") or "").strip(),
                    text=html_to_text(j.get("jobDescription")) or (j.get("jobExcerpt") or ""),
                    location=j.get("jobGeo") or "",
                    workplace_type="remote",
                    posted_at=from_iso(j.get("pubDate")),
                    salary=salary_text(j.get("salaryMin"), j.get("salaryMax"),
                                       j.get("salaryCurrency"), j.get("salaryPeriod")),
                ))
            cursor = data.get("nextCursor")
            if not data.get("hasMore") or not cursor:
                break
    return jobs


def _split_wwr_title(title: str) -> tuple[str, str]:
    company, sep, role = title.partition(":")
    return (role.strip(), company.strip()) if sep else (title.strip(), "")


def we_work_remotely(http: Http, feeds: list[str]) -> list[JobPosting]:
    jobs = []
    for feed in feeds:
        root = ET.fromstring(http.text(feed).encode("utf-8"))
        for item in root.iter("item"):
            get = lambda tag: (item.findtext(tag) or "").strip()  # noqa: E731
            role, company = _split_wwr_title(get("title"))
            try:
                posted = parsedate_to_datetime(get("pubDate")) if get("pubDate") else None
            except (TypeError, ValueError):
                posted = None
            jobs.append(JobPosting(
                source="WWR",
                url=get("link") or get("guid"),
                title=role,
                company=company,
                text=html_to_text(get("description")),
                location=get("region"),
                workplace_type="remote",
                posted_at=posted,
            ))
    return jobs
