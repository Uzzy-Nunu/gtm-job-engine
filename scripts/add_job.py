"""Add one job by link, from the command line (PRD §10.1).

The paste-a-link form and bookmarklet (Cloudflare Worker) do the same thing
from a browser or phone. This script is for testing and manual use.

Usage:
  python scripts/add_job.py --dry-run --demo           # made-up examples, fake HubSpot
  python scripts/add_job.py --dry-run "<link>" --text "post text"
  python scripts/add_job.py "<link>" --text-file post.txt   # real HubSpot (needs HUBSPOT_TOKEN)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, load_dotenv  # noqa: E402
from src.intake import Intake, Submission  # noqa: E402

DEMO = [
    ("Capture a LinkedIn post with text",
     Submission(url="https://www.linkedin.com/posts/jane-doe-123_hiring-activity-7390000000000000001-AbCd",
                text="Hiring a remote GTM Engineer. Apply: https://careers.samplecorp.example/jobs/42")),
    ("Same post again (different link style)",
     Submission(url="https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001")),
    ("Link only, no text",
     Submission(url="https://www.linkedin.com/posts/alex-sample-a1b2_gtm-ugcPost-7391111111111111111-Zz")),
    ("Same link again, now with the post text",
     Submission(url="https://www.linkedin.com/posts/alex-sample-a1b2_gtm-ugcPost-7391111111111111111-Zz",
                text="We're hiring a Growth Engineer, fully remote.")),
    ("Short lnkd.in link",
     Submission(url="https://lnkd.in/abc123")),
]


def show(label, result):
    flags = f"  [{', '.join(result.flags)}]" if result.flags else ""
    print(f"- {label}\n    {result.status.upper()}: {result.message}{flags}")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Add one job to HubSpot by link.")
    parser.add_argument("url", nargs="?")
    parser.add_argument("--text", default="")
    parser.add_argument("--text-file", type=Path)
    parser.add_argument("--notes", default="")
    parser.add_argument("--dry-run", action="store_true", help="use a fake HubSpot, change nothing")
    parser.add_argument("--demo", action="store_true", help="run made-up examples (needs --dry-run)")
    args = parser.parse_args(argv)

    if args.demo and not args.dry_run:
        parser.error("--demo only runs with --dry-run")
    if not args.demo and not args.url:
        parser.error("give a link, or use --dry-run --demo")

    if args.dry_run:
        hs = FakeHubSpot()
        print("DRY RUN: using a fake HubSpot. Nothing real is changed.\n")
    else:
        load_dotenv(ROOT / ".env")
        hs = HubSpotClient()
    intake = Intake(hs)

    results = []
    if args.demo:
        for label, sub in DEMO:
            result = intake.submit(sub)
            results.append(result)
            show(label, result)
    else:
        text = args.text_file.read_text(encoding="utf-8") if args.text_file else args.text
        result = intake.submit(Submission(url=args.url, text=text, notes=args.notes))
        results.append(result)
        show(args.url, result)

    if args.dry_run:
        print(f"\nFake HubSpot now holds: {len(hs.all('deals'))} deal(s), "
              f"{len(hs.all('contacts'))} contact(s), {len(hs.all('companies'))} company(ies).")
        for d in hs.all("deals"):
            p = d["properties"]
            print(f"  deal: {p['dealname']}  |  stage: {hs.stage_label(p['dealstage'])}"
                  f"  |  source: {p['job_source']}")
    return 0 if all(r.ok for r in results if not args.demo) else 1


if __name__ == "__main__":
    sys.exit(main())
