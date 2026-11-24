"""Daily job-board import (PRD §10.1 IN-3, IN-4, IN-8).

1. Read every configured board. One failing board is recorded as an error
   and the rest carry on (PRD §13 reliability).
2. Keep only recent jobs with a matching title and a location Peace can work
   from. Target titles go first, then newest first.
3. Send each to Intake (which handles duplicates) until the daily cap of new
   deals from job boards is reached. Duplicates don't use up the cap.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from src.intake import Intake, Submission
from src.job_filter import TitleFilter, is_recent, looks_remote, region_ok
from src.sources import company_boards, remote_boards
from src.sources import feeds as generic_feeds
from src.sources import linkedin_alerts
from src.sources.base import JobPosting
from src.urls import URLError, normalise_url

BOARD_SOURCES = ["Greenhouse", "Lever", "Ashby", "RemoteOK", "Himalayas", "WWR",
                 "Remotive", "Jobicy", "Other", "LinkedIn Alert"]


@dataclass
class ImportReport:
    fetched: dict[str, int] = field(default_factory=dict)
    kept: int = 0
    skipped: dict[str, int] = field(default_factory=lambda: {
        "title": 0, "location": 0, "too old": 0, "repeat in this run": 0, "bad link": 0})
    created: list[str] = field(default_factory=list)
    duplicates: int = 0
    updated: int = 0
    not_imported_cap: int = 0
    errors: list[str] = field(default_factory=list)
    alerts: linkedin_alerts.AlertStats | None = None
    cap: int = 0
    already_today: int = 0
    matched_by_list: dict[str, int] = field(default_factory=lambda: {"target": 0, "adjacent": 0, "explore": 0})
    created_by_list: dict[str, int] = field(default_factory=lambda: {"target": 0, "adjacent": 0, "explore": 0})
    # Remote, eligible, recent jobs skipped only because the title isn't on a list:
    # the place to look for titles worth adding.
    near_misses: Counter = field(default_factory=Counter)

    @property
    def ok(self) -> bool:
        return not self.errors

    def lines(self) -> list[str]:
        out = ["Fetched: " + (", ".join(f"{k} {v}" for k, v in self.fetched.items()) or "nothing")]
        out.append(f"Matched filters: {self.kept} | skipped: "
                   + ", ".join(f"{k} {v}" for k, v in self.skipped.items() if v))
        out.append("Matches by title list: " + ", ".join(
            f"{k} {self.matched_by_list[k]} (new {self.created_by_list[k]})" for k in self.matched_by_list))
        if self.alerts:
            out.append(self.alerts.line())
        out.append(f"Daily cap: {self.cap} (already imported today: {self.already_today})")
        out.append(f"New deals: {len(self.created)} | duplicates: {self.duplicates} | "
                   f"updated: {self.updated} | left for tomorrow (cap): {self.not_imported_cap}")
        out += [f"  + {name}" for name in self.created]
        out += [f"  ! {err}" for err in self.errors]
        if self.near_misses:
            out.append(f"Remote and recent, skipped only for the title ({sum(self.near_misses.values())}); "
                       "most common:")
            out += [f"  ? {title} ({n})" if n > 1 else f"  ? {title}"
                    for title, n in self.near_misses.most_common(NEAR_MISS_SHOWN)]
        return out


def collect(config: dict, http, report: ImportReport, mailbox=None) -> list[JobPosting]:
    """Fetch from every configured board, isolating failures. `mailbox` reads
    LinkedIn job-alert emails when `linkedin_alerts.enabled` is true."""
    jobs: list[JobPosting] = []
    readers = []
    companies = config.get("companies") or {}
    for kind in ("greenhouse", "lever", "ashby"):
        for entry in companies.get(kind) or []:
            label = f"{kind.title()} {company_boards.board_entry(entry)['token']}"
            readers.append((label, lambda k=kind, e=entry: getattr(company_boards, k)(http, e)))
    feeds = config.get("public_feeds") or {}
    opts = config.get("import") or {}
    if feeds.get("remoteok"):
        readers.append(("RemoteOK", lambda: remote_boards.remoteok(http)))
    if feeds.get("himalayas"):
        queries = list(opts.get("himalayas_queries") or (
            list(config.get("target_titles") or []) + list(config.get("adjacent_titles") or [])))
        explore = (config.get("explore_titles") or []) if opts.get("himalayas_search_explore", True) else []
        for title in explore:
            if title.lower() not in {q.lower() for q in queries}:
                queries.append(title)
        readers.append(("Himalayas", lambda: remote_boards.himalayas(
            http, queries, int(opts.get("himalayas_pages", 2)))))
    if feeds.get("we_work_remotely"):
        readers.append(("WWR", lambda: remote_boards.we_work_remotely(http, opts.get("wwr_feeds") or [])))
    if feeds.get("remotive"):
        readers.append(("Remotive", lambda: remote_boards.remotive(http)))
    if feeds.get("jobicy"):
        readers.append(("Jobicy", lambda: remote_boards.jobicy(
            http, opts.get("jobicy_geos") or ["anywhere"], int(opts.get("jobicy_pages", 3)))))
    for feed in config.get("extra_feeds") or []:
        if feed.get("enabled", True) is False or not feed.get("url"):
            continue
        readers.append((feed.get("name") or feed["url"], lambda f=feed: generic_feeds.read_feed(http, f)))

    if (config.get("linkedin_alerts") or {}).get("enabled") and mailbox is not None:
        report.alerts = linkedin_alerts.AlertStats()
        readers.append(("LinkedIn alerts",
                        lambda: linkedin_alerts.read_alerts(http, config, mailbox, report.alerts)))

    for label, read in readers:
        try:
            found = read()
            report.fetched[label] = len(found)
            jobs.extend(found)
        except Exception as e:  # noqa: BLE001 - one board must not stop the rest
            report.errors.append(f"{label}: {e}")
    return jobs


RANK = {"target": 0, "adjacent": 1, "explore": 2}
NEAR_MISS_SHOWN = 40
COMPANY_BOARD_SOURCES = ("Greenhouse", "Lever", "Ashby")


def select(jobs: list[JobPosting], config: dict, report: ImportReport,
           now=None) -> list[tuple[str, JobPosting]]:
    """Filtered jobs as (title list, job), best list first, then newest first."""
    titles = TitleFilter.from_config(config)
    eligible = config.get("eligible_regions") or []
    max_age = int((config.get("import") or {}).get("max_job_age_days", 14))
    # A company's own board lists only open roles, so older postings are still live.
    board_age = int((config.get("import") or {}).get("company_board_max_age_days", 60))
    seen: set[str] = set()
    ranked = []
    for job in jobs:
        age = board_age if job.source in COMPANY_BOARD_SOURCES else max_age
        rank = titles.match(job.title)
        if not rank:
            report.skipped["title"] += 1
            if (looks_remote(job.location, job.workplace_type) and region_ok(job.location, eligible)
                    and is_recent(job.posted_at, age, now)):
                report.near_misses[" ".join((job.title or "").split())[:80]] += 1
            continue
        if not looks_remote(job.location, job.workplace_type) or not region_ok(job.location, eligible):
            report.skipped["location"] += 1
            continue
        if not is_recent(job.posted_at, age, now):
            report.skipped["too old"] += 1
            continue
        try:
            key = normalise_url(job.url)
        except URLError:
            report.skipped["bad link"] += 1
            continue
        if key in seen:
            report.skipped["repeat in this run"] += 1
            continue
        seen.add(key)
        report.matched_by_list[rank] += 1
        ranked.append((rank, job))
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    ranked.sort(key=lambda r: (RANK[r[0]], -(r[1].posted_at or oldest).timestamp()))
    report.kept = len(ranked)
    return ranked


def to_submission(job: JobPosting, title_list: str = "target") -> Submission:
    header = [f"{job.title} at {job.company}".strip()]
    if job.location:
        header.append(f"Location: {job.location}")
    if job.salary:
        header.append(f"Salary: {job.salary}")
    if job.posted_at:
        header.append(f"Posted: {job.posted_at:%d %b %Y}")
    header.append(f"Source: {job.source}")
    header.append(f"Matched title list: {title_list}")
    return Submission(
        url=job.url, text="\n".join(header) + "\n\n" + (job.text or ""), source=job.source,
        title=job.title or None, company=job.company or None,
        company_website=job.company_website, apply_url=job.apply_url, needs_text=job.needs_text,
    )


def imported_today(hs, tz: str, now: datetime) -> int:
    local_midnight = datetime.combine(now.astimezone(ZoneInfo(tz)).date(), time.min, ZoneInfo(tz))
    since = str(int(local_midnight.timestamp() * 1000))  # HubSpot compares dates in ms
    found = hs.post("/crm/v3/objects/deals/search", {
        "filterGroups": [{"filters": [
            {"propertyName": "createdate", "operator": "GTE", "value": since},
            {"propertyName": "job_source", "operator": "IN", "values": BOARD_SOURCES},
        ]}],
        "limit": 1,
    })
    return int((found or {}).get("total", 0))


def run_import(config: dict, hs, http, now: datetime | None = None, mailbox=None) -> ImportReport:
    now = now or datetime.now(timezone.utc)
    report = ImportReport(cap=int(config.get("daily_import_cap", 40)))
    jobs = select(collect(config, http, report, mailbox), config, report, now)

    try:
        report.already_today = imported_today(hs, config.get("timezone", "UTC"), now)
    except Exception as e:  # noqa: BLE001
        report.errors.append(f"HubSpot: could not count today's imports: {e}")
        return report
    room = max(0, report.cap - report.already_today)

    intake = Intake(hs, int(config.get("duplicate_window_days", 14)), now=lambda: now)
    for i, (title_list, job) in enumerate(jobs):
        if len(report.created) >= room:
            report.not_imported_cap = len(jobs) - i
            break
        result = intake.submit(to_submission(job, title_list))
        if result.status == "created":
            tag = " [explore]" if title_list == "explore" else ""
            report.created.append(f"{job.title} - {job.company} ({job.source}){tag}")
            report.created_by_list[title_list] += 1
        elif result.status == "duplicate":
            report.duplicates += 1
        elif result.status == "updated":
            report.updated += 1
        else:
            report.errors.append(f"{job.source} {job.url}: {result.message}")
    return report
