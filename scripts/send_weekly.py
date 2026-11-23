"""Send the Monday weekly summary email (PRD §10.6 DG-3).

Modes:
  python scripts/send_weekly.py --offline   # made-up deals; prints the email, sends nothing
  python scripts/send_weekly.py --preview   # real HubSpot; numbers in the log, nothing sent
  python scripts/send_weekly.py             # real HubSpot; emails the summary via Gmail

Reads HubSpot only. The summary holds numbers, no deal names.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, HubSpotError, load_dotenv  # noqa: E402
from src.mailer import GmailMailer, MailError  # noqa: E402
from src.weekly import WeeklyBuilder  # noqa: E402


def offline_hubspot() -> FakeHubSpot:
    hs = FakeHubSpot()
    stage = {s["label"]: s["id"] for s in hs.pipeline["stages"]}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    samples = [
        ("New", {}), ("Archived", {}), ("Archived", {}), ("Qualified", {}),
        ("Ready for Review", {"keyword_coverage": "92"}),
        ("Ready for Review", {"keyword_coverage": "70", "pipeline_error": "TRUTH CHECK: 1 issue(s)."}),
        ("Applied", {"keyword_coverage": "85", "applied_date": today}),
        ("Interviewing", {"keyword_coverage": "88"}),
    ]
    for i, (label, props) in enumerate(samples):
        hs.post("/crm/v3/objects/deals", {"properties": {
            "dealname": f"Sample job {i}", "pipeline": "default", "dealstage": stage[label], **props}})
    old = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for rec in hs.objects["deals"].values():
        if rec["properties"]["dealstage"] == stage["Interviewing"]:
            rec["properties"]["createdate"] = old
    return hs


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Send the weekly summary email.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="made-up deals; print the email, send nothing")
    mode.add_argument("--preview", action="store_true", help="real HubSpot; numbers in the log, send nothing")
    args = parser.parse_args(argv)
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    mailer = None
    if args.offline:
        label, hs = "OFFLINE DEMO (made-up deals, nothing sent)", offline_hubspot()
    else:
        load_dotenv(ROOT / ".env")
        hs = HubSpotClient()
        label = "PREVIEW (real HubSpot, nothing sent)" if args.preview else "LIVE (summary emailed)"
        if not args.preview:
            try:
                mailer = GmailMailer()
            except MailError as e:
                print(f"== Weekly summary: {label}\n! {e}")
                return 1

    print(f"== Weekly summary: {label}")
    try:
        weekly = WeeklyBuilder(hs, config).build()
    except HubSpotError as e:
        print(f"! Couldn't read HubSpot: {e}")
        return 1
    lines = weekly.log_lines()
    print(weekly.subject + "\n" + "\n".join(lines))

    if mailer:
        try:
            mailer.send(weekly.subject, weekly.text(), weekly.html())
        except MailError as e:
            print(f"! {e}")
            return 1
        print("Summary emailed.")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## Weekly summary: {label}\n\n```\n" + "\n".join(lines) + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
