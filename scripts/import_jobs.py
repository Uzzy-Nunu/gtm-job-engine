"""Import new jobs from the job boards into HubSpot (PRD §10.1 IN-3).

Usage:
  python scripts/import_jobs.py --dry-run --offline   # made-up board data, fake HubSpot
  python scripts/import_jobs.py --dry-run              # real boards, fake HubSpot
  python scripts/import_jobs.py                        # real boards, real HubSpot

Exits with code 1 when any board or HubSpot call failed, so the scheduled
GitHub run turns red and GitHub emails a failure notice (PRD OP-3).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, load_dotenv  # noqa: E402
from src.importer import run_import  # noqa: E402
from src.sources.base import Http, SourceError  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "boards"
OFFLINE_ROUTES = {
    "https://boards-api.greenhouse.io/": "greenhouse.json",
    "https://api.lever.co/": "lever.json",
    "https://api.ashbyhq.com/": "ashby.json",
    "https://remoteok.com/api": "remoteok.json",
    "https://himalayas.app/jobs/api": "himalayas.json",
    "https://weworkremotely.com/": "wwr.rss",
    "https://remotive.com/api/remote-jobs": "remotive.json",
    "https://jobicy.com/api/jobs": "jobicy.json",
}
OFFLINE_COMPANIES = {"greenhouse": ["samplecorp"], "lever": ["demo-co"],
                     "ashby": [{"token": "fictional", "name": "Fictional AI",
                                "website": "https://fictional.example"}]}


def apply_offline_settings(config: dict, keep_dates: bool = True) -> dict:
    """Point the config at the sample boards. One WWR feed, since every WWR
    URL is served the same sample file."""
    config["companies"] = OFFLINE_COMPANIES
    opts = config.setdefault("import", {})
    opts["wwr_feeds"] = (opts.get("wwr_feeds") or ["https://weworkremotely.com/sample.rss"])[:1]
    opts["himalayas_queries"] = ["sample"]  # the sample file is served for any search
    opts["jobicy_geos"] = ["anywhere"]      # the sample file is served for any region
    config["extra_feeds"] = []              # offline mode never touches real boards
    config["explore_titles"] = []           # keep sample results stable whatever Peace explores
    if not keep_dates:
        opts["max_job_age_days"] = 100_000  # sample dates get older every day
    return config


class OfflineHttp:
    """Serves made-up board responses from tests/fixtures/boards."""

    def _file(self, url):
        for prefix, name in OFFLINE_ROUTES.items():
            if url.startswith(prefix):
                return FIXTURES / name
        raise SourceError(f"No offline fixture for {url}")

    def json(self, url, params=None):
        data = json.loads(self._file(url).read_text(encoding="utf-8"))
        if url.startswith("https://himalayas.app") and params and params.get("offset"):
            return {"jobs": []}
        return data

    def text(self, url, params=None):
        return self._file(url).read_text(encoding="utf-8")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Import jobs from job boards.")
    parser.add_argument("--dry-run", action="store_true", help="fake HubSpot, change nothing")
    parser.add_argument("--offline", action="store_true", help="made-up board data, no internet")
    args = parser.parse_args(argv)

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if args.offline:
        apply_offline_settings(config, keep_dates=False)
        http = OfflineHttp()
    else:
        http = Http()

    if args.dry_run:
        hs = FakeHubSpot()
    else:
        load_dotenv(ROOT / ".env")
        hs = HubSpotClient()

    mailbox = None
    if not args.offline:
        from src.sources.linkedin_alerts import GmailAlerts
        gmail = GmailAlerts()
        mailbox = gmail if gmail.configured else None
        if (config.get("linkedin_alerts") or {}).get("enabled") and mailbox is None:
            print("! LinkedIn alerts are on in config.yaml, but no Gmail secrets are set "
                  "(ALERTS_GMAIL_ADDRESS / ALERTS_GMAIL_APP_PASSWORD, or GMAIL_ADDRESS / GMAIL_APP_PASSWORD).")

    mode = ("DRY RUN (fake HubSpot)" if args.dry_run else "LIVE (real HubSpot)") + \
           (", offline sample data" if args.offline else "")
    print(f"== Job board import: {mode}")
    report = run_import(config, hs, http, mailbox=mailbox)
    lines = report.lines()
    print("\n".join(lines))

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"## Job board import: {mode}\n\n```\n" + "\n".join(lines) + "\n```\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
