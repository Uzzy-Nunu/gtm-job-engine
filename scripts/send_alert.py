"""Email an alert when a scheduled workflow fails (PRD §10.7 OP-3).

Called from the last step of each scheduled workflow, only on failure:
  python scripts/send_alert.py "Import jobs"

The email holds the workflow name and a link to the run, nothing else. Uses
GITHUB_SERVER_URL, GITHUB_REPOSITORY and GITHUB_RUN_ID, which GitHub provides.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mailer import GmailMailer, MailError  # noqa: E402


def alert_text(workflow: str, run_url: str) -> tuple[str, str]:
    subject = f"GTM Job Engine: '{workflow}' failed"
    text = (f"The scheduled '{workflow}' run failed.\n\n"
            f"Open the run to see which step failed and why:\n{run_url}\n\n"
            "Deals that hit a problem are marked in HubSpot (Pipeline Error) and listed in "
            "tomorrow's digest. Nothing was applied or sent.")
    return subject, text


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    workflow = argv[0] if argv else os.environ.get("GITHUB_WORKFLOW", "A workflow")
    run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
               f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}")
    subject, text = alert_text(workflow, run_url)
    try:
        GmailMailer().send(subject, text)
    except MailError as e:
        print(f"! Alert not sent: {e}")
        return 1
    print("Alert emailed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
