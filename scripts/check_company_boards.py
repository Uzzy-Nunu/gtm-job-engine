"""Check company job boards before adding them to config.yaml (hiring signal check).

For each candidate it finds the board on Greenhouse, Lever or Ashby and counts:
  - open jobs in total
  - remote jobs open to your regions, posted in the last `import.company_board_max_age_days`
    (default 60: a company's own board lists only open roles)
  - of those, jobs whose title matches your title lists (what the importer would bring in)

Usage:
  python scripts/check_company_boards.py candidates.txt [--csv out.csv]
  python scripts/check_company_boards.py --token greenhouse:gitlab --token ashby:posthog

A candidates file has one company per line:  Name | ats | token
where ats is greenhouse, lever, ashby, or "any" to try all three. Lines starting
with # are ignored. Only public job-board APIs are used; nothing is written anywhere.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.job_filter import TitleFilter, is_recent, looks_remote, region_ok  # noqa: E402
from src.sources import company_boards  # noqa: E402
from src.sources.base import Http, SourceError  # noqa: E402

KINDS = ("greenhouse", "lever", "ashby")


@dataclass
class BoardCheck:
    name: str
    kind: str = ""
    token: str = ""
    total: int = 0
    remote_recent: int = 0
    matching: int = 0
    titles: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def found(self) -> bool:
        return bool(self.kind) and not self.error


def parse_candidates(text: str) -> list[tuple[str, str, str]]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and parts[2] and parts[2] != "-":
            out.append((parts[0], parts[1].lower(), parts[2]))
    return out


def check(http, name: str, ats: str, token: str, config: dict, now=None) -> BoardCheck:
    titles = TitleFilter.from_config(config)
    eligible = config.get("eligible_regions") or []
    max_age = int((config.get("import") or {}).get("company_board_max_age_days", 60))
    result = BoardCheck(name=name, token=token)
    last_error = ""
    for kind in (KINDS if ats in ("any", "unknown", "") else (ats,)):
        if kind not in KINDS:
            result.error = f"unsupported ATS '{kind}'"
            return result
        try:
            jobs = getattr(company_boards, kind)(http, token)
        except (SourceError, Exception) as e:  # noqa: BLE001 - try the next ATS
            last_error = f"{kind}: {type(e).__name__}"
            continue
        result.kind, result.total = kind, len(jobs)
        for job in jobs:
            if not (looks_remote(job.location, job.workplace_type) and region_ok(job.location, eligible)
                    and is_recent(job.posted_at, max_age, now)):
                continue
            result.remote_recent += 1
            if titles.match(job.title):
                result.matching += 1
                result.titles.append(job.title.strip())
        return result
    result.error = last_error or "board not found"
    return result


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check company job boards for live, matching remote roles.")
    parser.add_argument("candidates", nargs="?", help="file with lines: Name | ats | token")
    parser.add_argument("--token", action="append", default=[], help="ats:token, e.g. greenhouse:gitlab")
    parser.add_argument("--csv", help="also write the results to this CSV file")
    args = parser.parse_args(argv)
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    todo = parse_candidates(Path(args.candidates).read_text(encoding="utf-8")) if args.candidates else []
    for item in args.token:
        ats, _, token = item.partition(":")
        todo.append((token, ats.lower(), token))
    if not todo:
        parser.error("give a candidates file or --token ats:token")

    http = Http(retries=1)
    now = datetime.now(timezone.utc)
    results = []
    for name, ats, token in todo:
        r = check(http, name, ats, token, config, now)
        results.append(r)
        status = (f"{r.kind:<10} jobs {r.total:>4} | remote+recent {r.remote_recent:>3} | matching {r.matching:>2}"
                  if r.found else f"not found ({r.error})")
        print(f"{name[:32]:<32} {token[:24]:<24} {status}")
        for t in r.titles[:5]:
            print(f"    + {t}")

    found = [r for r in results if r.found]
    print(f"\nBoards found: {len(found)} of {len(results)} | with remote+recent roles: "
          f"{sum(1 for r in found if r.remote_recent)} | with matching roles: {sum(1 for r in found if r.matching)}"
          f" | matching roles in total: {sum(r.matching for r in found)}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["name", "ats", "token", "total_jobs", "remote_recent", "matching", "matching_titles", "error"])
            for r in results:
                w.writerow([r.name, r.kind, r.token, r.total, r.remote_recent, r.matching,
                            "; ".join(r.titles), r.error])
    return 0


if __name__ == "__main__":
    sys.exit(main())
