"""Qualify new jobs in HubSpot (PRD §10.2).

Modes:
  python scripts/qualify_jobs.py --offline   # made-up jobs, fake AI, fake HubSpot (no keys needed)
  python scripts/qualify_jobs.py --preview   # real New deals + real AI, but WRITES NOTHING
  python scripts/qualify_jobs.py             # live: updates HubSpot

Needs HUBSPOT_TOKEN, LLM_API_KEY and MASTER_CV (or MASTER_CV_PATH) except in
--offline mode. Prints job titles and companies only: never CV content or
poster names (GitHub Actions logs on a public repo are public).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.cv_sections import qualify_profile  # noqa: E402
from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, load_dotenv  # noqa: E402
from src.llm import FakeProvider, make_llm, exit_code  # noqa: E402
from src.qualify import Qualifier  # noqa: E402
from src.sources.base import Http  # noqa: E402

SAMPLES = ROOT / "tests" / "fixtures" / "qualify_samples.json"
SAMPLE_CV = ROOT / "tests" / "fixtures" / "sample_cv_profile.md"


def offline_setup():
    samples = {s["id"]: s for s in json.loads(SAMPLES.read_text(encoding="utf-8"))["samples"]}
    hs = FakeHubSpot()
    new = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == "New")
    for i, (sid, s) in enumerate(samples.items()):
        hs.post("/crm/v3/objects/deals", {"properties": {
            "dealname": f"Sample job {sid}", "pipeline": "default", "dealstage": new,
            "job_source": "Other", "job_url": f"https://jobs.example/{sid}",
            "description": f"Ref {sid}. {s['description']}"}})

    def answer(system, prompt, schema):
        return samples[re.search(r"Ref (s\d+)\.", prompt).group(1)]["ai"]

    profile = qualify_profile(SAMPLE_CV.read_text(encoding="utf-8"))
    return hs, FakeProvider(answer), profile


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Qualify new jobs in HubSpot.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="made-up jobs, fake AI and HubSpot")
    mode.add_argument("--preview", action="store_true", help="real data and AI, but write nothing")
    parser.add_argument("--rescore-archived", action="store_true",
                        help="re-score Archived deals that were archived for a low fit score")
    args = parser.parse_args(argv)

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    max_calls = int((config.get("llm") or {}).get("max_ai_calls_per_run", 40))

    if args.offline:
        hs, llm, profile = offline_setup()
        label, write = "OFFLINE DEMO (made-up jobs, fake AI, fake HubSpot)", True
    else:
        load_dotenv(ROOT / ".env")
        hs, llm, profile = HubSpotClient(), make_llm(config), qualify_profile()
        label = "PREVIEW (real data and AI, nothing written)" if args.preview else "LIVE (updates HubSpot)"
        write = not args.preview

    if args.rescore_archived:
        label += " | RE-SCORING low-score Archived deals"
    print(f"== Qualify jobs: {label}")
    report = Qualifier(hs, llm, config, profile, http=Http(), write=write,
                       rescore_archived=args.rescore_archived).run(max_ai_calls=max_calls)
    lines = report.lines()
    print("\n".join(lines))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## Qualify jobs: {label}\n\n```\n" + "\n".join(lines) + "\n```\n")
    return exit_code(report.count("error") > 0, report.stopped)


if __name__ == "__main__":
    sys.exit(main())
