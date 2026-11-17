"""Draft tailored applications for Researched deals (PRD §10.4).

Modes:
  python scripts/draft_jobs.py --offline   # made-up CV, job and AI answers; files in output/drafts/offline
  python scripts/draft_jobs.py --preview   # real deals, master CV and AI; files in output/drafts, HubSpot untouched
  python scripts/draft_jobs.py             # live (Milestone 5 part 3): files attached in HubSpot

Needs HUBSPOT_TOKEN, LLM_API_KEY and MASTER_CV (or MASTER_CV_PATH) except in
--offline mode. The log shows counts and scores only, never CV text, letters or
messages. Draft files are never published as GitHub artifacts (the repo is public).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.cv_sections import load_text  # noqa: E402
from src.draft import Drafter  # noqa: E402
from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, load_dotenv  # noqa: E402
from src.llm import FakeProvider, make_llm  # noqa: E402

OUT = ROOT / "output" / "drafts"
SAMPLE_CV = ROOT / "tests" / "fixtures" / "sample_cv_full.md"


def offline_setup():
    sys.path.insert(0, str(ROOT / "tests"))
    from tests.test_draft import DRAFT  # made-up AI answer used by the tests

    hs = FakeHubSpot()
    researched = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == "Researched")
    hs.post("/crm/v3/objects/deals", {"properties": {
        "dealname": "GTM Engineer - SampleCorp", "pipeline": "default", "dealstage": researched,
        "fit_score": "90", "job_url": "https://jobs.example/1",
        "description": "SampleCorp needs a GTM Engineer for outbound automation with Clay and HubSpot.",
        "job_analysis": "Fit score: 90/100\n\nCompany brief:\n- SampleCorp sells analytics software."}})

    def answer(system, prompt, schema):
        return {"issues": []} if "fact-checker" in system else DRAFT

    return hs, FakeProvider(answer), SAMPLE_CV.read_text(encoding="utf-8")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Draft tailored applications.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="made-up data, fake AI and HubSpot")
    mode.add_argument("--preview", action="store_true", help="real data and AI; files saved locally only")
    args = parser.parse_args(argv)

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    max_calls = int((config.get("llm") or {}).get("max_ai_calls_per_run", 40))
    if args.offline:
        hs, llm, master = offline_setup()
        label, out = "OFFLINE DEMO (made-up CV, job and AI answers)", OUT / "offline"
    elif args.preview:
        load_dotenv(ROOT / ".env")
        hs, llm, master = HubSpotClient(), make_llm(config), load_text()
        label, out = "PREVIEW (real data and AI; files saved locally, HubSpot untouched)", OUT
    else:
        print("Live drafting (files attached in HubSpot) arrives in Milestone 5 part 3. "
              "Use --preview or --offline for now.")
        return 2

    print(f"== Draft jobs: {label}")
    report = Drafter(hs, llm, config, master, out, write=False).run(max_ai_calls=max_calls)
    lines = report.lines()
    print("\n".join(lines))
    if report.drafts and not os.environ.get("GITHUB_ACTIONS"):
        print(f"\nFiles saved in {out} (private, git-ignored).")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## Draft jobs: {label}\n\n```\n" + "\n".join(lines) + "\n```\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
