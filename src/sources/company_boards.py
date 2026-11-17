"""Readers for company job boards hosted on Greenhouse, Lever and Ashby.

Each company is listed in config.yaml under `companies:` as a board token,
or as {token, name, website} when the board doesn't say.
"""

from __future__ import annotations

from src.sources.base import (Http, JobPosting, from_epoch, from_iso,
                              html_to_text)


def board_entry(entry) -> dict:
    if isinstance(entry, str):
        return {"token": entry.strip(), "name": None, "website": None}
    return {"token": str(entry["token"]).strip(), "name": entry.get("name"),
            "website": entry.get("website")}


def _pretty(token: str) -> str:
    return token.replace("-", " ").replace("_", " ").title()


def greenhouse(http: Http, entry) -> list[JobPosting]:
    """https://developers.greenhouse.io/job-board.html"""
    b = board_entry(entry)
    data = http.json(f"https://boards-api.greenhouse.io/v1/boards/{b['token']}/jobs",
                     params={"content": "true"})
    jobs = []
    for j in data.get("jobs", []):
        jobs.append(JobPosting(
            source="Greenhouse",
            url=j.get("absolute_url") or "",
            title=(j.get("title") or "").strip(),
            company=b["name"] or j.get("company_name") or _pretty(b["token"]),
            text=html_to_text(j.get("content")),
            location=((j.get("location") or {}).get("name") or ""),
            company_website=b["website"],
            posted_at=from_iso(j.get("first_published") or j.get("updated_at")),
        ))
    return jobs


def lever(http: Http, entry) -> list[JobPosting]:
    """https://github.com/lever/postings-api"""
    b = board_entry(entry)
    data = http.json(f"https://api.lever.co/v0/postings/{b['token']}", params={"mode": "json"})
    jobs = []
    for j in data if isinstance(data, list) else []:
        parts = [j.get("descriptionPlain") or ""]
        for block in j.get("lists") or []:
            parts.append(f"{block.get('text', '')}\n{html_to_text(block.get('content'))}")
        parts.append(j.get("additionalPlain") or "")
        cats = j.get("categories") or {}
        jobs.append(JobPosting(
            source="Lever",
            url=j.get("hostedUrl") or "",
            title=(j.get("text") or "").strip(),
            company=b["name"] or _pretty(b["token"]),
            text="\n\n".join(p.strip() for p in parts if p and p.strip()),
            location=cats.get("location") or ", ".join(cats.get("allLocations") or []),
            workplace_type=j.get("workplaceType") or "",
            apply_url=j.get("applyUrl"),
            company_website=b["website"],
            posted_at=from_epoch(j.get("createdAt")),
        ))
    return jobs


def _ashby_locations(job: dict) -> str:
    names = [job.get("location") or ""]
    for extra in job.get("secondaryLocations") or []:
        names.append(extra.get("location", "") if isinstance(extra, dict) else str(extra))
    return ", ".join(n for n in names if n)


def ashby(http: Http, entry) -> list[JobPosting]:
    """https://developers.ashbyhq.com/docs/public-job-posting-api"""
    b = board_entry(entry)
    data = http.json(f"https://api.ashbyhq.com/posting-api/job-board/{b['token']}",
                     params={"includeCompensation": "true"})
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        workplace = j.get("workplaceType") or ("Remote" if j.get("isRemote") else "")
        jobs.append(JobPosting(
            source="Ashby",
            url=j.get("jobUrl") or "",
            title=(j.get("title") or "").strip(),
            company=b["name"] or _pretty(b["token"]),
            text=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            location=_ashby_locations(j),
            workplace_type=workplace,
            apply_url=j.get("applyUrl"),
            company_website=b["website"],
            posted_at=from_iso(j.get("publishedAt")),
            salary=comp,
        ))
    return jobs
