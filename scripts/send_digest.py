"""Send the daily digest email (PRD §10.6).

Modes:
  python scripts/send_digest.py --offline   # made-up deals; prints the email, sends nothing
  python scripts/send_digest.py --preview   # real HubSpot; log shows counts only, nothing sent
  python scripts/send_digest.py             # real HubSpot; emails the digest via Gmail

Before the digest is built, Applied deals with no update for `digest.follow_up_days`
get a follow-up task in HubSpot (send mode only; preview counts what it would add).

Needs HUBSPOT_TOKEN, GMAIL_ADDRESS, GMAIL_APP_PASSWORD (and optionally
DIGEST_TO_EMAIL) except in --offline mode. The only HubSpot change is adding
follow-up tasks; deals themselves are never changed.
The log never shows deal names (the repo is public); only the email does.
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

from src.digest import DigestBuilder  # noqa: E402
from src.followups import FollowUpTasks  # noqa: E402
from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, HubSpotError, load_dotenv  # noqa: E402
from src.mailer import FakeMailer, GmailMailer, MailError  # noqa: E402

PREVIEW_FILE = ROOT / "output" / "digest-preview.html"


def offline_hubspot() -> FakeHubSpot:
    hs = FakeHubSpot()
    stage = {s["label"]: s["id"] for s in hs.pipeline["stages"]}
    samples = [
        ("GTM Engineer - SampleCorp", "Ready for Review", {"fit_score": "88", "keyword_coverage": "92"}),
        ("RevOps Manager - Example Ltd", "Ready for Review",
         {"fit_score": "74", "keyword_coverage": "80", "pipeline_error": "TRUTH CHECK: 1 issue(s) in the drafts."}),
        ("Growth Lead - Demo Inc", "Applied", {"fit_score": "81"}),
        ("Marketing Ops - TBC", "New", {"pipeline_error": "NEEDS POST TEXT: paste the post text"}),
        ("AI Automation Lead - Acme", "Researched", {"fit_score": "70"}),
    ]
    for name, label, props in samples:
        hs.post("/crm/v3/objects/deals", {"properties": {
            "dealname": name, "pipeline": "default", "dealstage": stage[label], **props}})
    old = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for rec in hs.objects["deals"].values():
        if rec["properties"]["dealstage"] == stage["Applied"]:
            rec["properties"]["hs_lastmodifieddate"] = old
    return hs


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Send the daily digest email.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="made-up deals; print the email, send nothing")
    mode.add_argument("--preview", action="store_true", help="real HubSpot; counts only, send nothing")
    args = parser.parse_args(argv)
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    if args.offline:
        label, hs, mailer = "OFFLINE DEMO (made-up deals, nothing sent)", offline_hubspot(), FakeMailer()
    else:
        load_dotenv(ROOT / ".env")
        hs = HubSpotClient()
        if args.preview:
            label, mailer = "PREVIEW (real HubSpot, nothing sent)", None
        else:
            label = "LIVE (digest emailed)"
            try:
                mailer = GmailMailer()
            except MailError as e:
                print(f"== Daily digest: {label}\n! {e}")
                return 1

    print(f"== Daily digest: {label}")
    write_tasks = not args.preview   # offline writes only to the in-memory fake
    try:
        tasks = FollowUpTasks(hs, config).run(write=write_tasks)
        digest = DigestBuilder(hs, config).build()
    except HubSpotError as e:
        print(f"! Couldn't read HubSpot: {e}")
        return 1
    for line in digest.follow_ups:
        line.task = line.id in tasks.task_deal_ids
    if tasks.errors:
        digest.notes.append(f"Couldn't add {len(tasks.errors)} follow-up task(s) in HubSpot: {tasks.errors[0]} "
                            "(see docs/runbook.md > Troubleshooting).")
    lines = [tasks.line(write=write_tasks)] + digest.log_lines()
    print("\n".join(lines))

    if args.offline:
        print("\n--- email (made-up data) ---\nSubject: " + digest.subject + "\n\n" + digest.text())
    elif args.preview:
        if not os.environ.get("GITHUB_ACTIONS"):
            PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
            PREVIEW_FILE.write_text(digest.html(), encoding="utf-8")
            print(f"\nPreview saved to {PREVIEW_FILE} (private, git-ignored). Open it in your browser.")
    else:
        try:
            mailer.send(digest.subject, digest.text(), digest.html())
        except MailError as e:
            print(f"! {e}")
            return 1
        print("Digest emailed.")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## Daily digest: {label}\n\n```\n" + "\n".join(lines) + "\n```\n")
    if tasks.errors:
        print("! Follow-up tasks failed (the digest itself was built): " + tasks.errors[0])
        return 1   # red run + alert email, so a missing HubSpot scope gets noticed
    return 0


if __name__ == "__main__":
    sys.exit(main())
