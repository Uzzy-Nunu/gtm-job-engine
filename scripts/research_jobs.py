"""Research qualified jobs in HubSpot (PRD §10.3).

Modes:
  python scripts/research_jobs.py --offline   # made-up deals and websites, fake AI and HubSpot
  python scripts/research_jobs.py --preview   # real Qualified deals + real AI, but WRITES NOTHING
  python scripts/research_jobs.py             # live: briefs saved, deals moved to Researched

Needs HUBSPOT_TOKEN and LLM_API_KEY except in --offline mode. Logs show job
titles and companies only, never poster names.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, load_dotenv  # noqa: E402
from src.llm import FakeProvider, make_llm  # noqa: E402
from src.research import Researcher  # noqa: E402
from src.sources.base import Http  # noqa: E402


class OfflineHttp:
    def text(self, url, params=None):
        if url == "https://samplecorp.example":
            return "<h1>SampleCorp</h1><p>Revenue analytics for B2B SaaS teams.</p>" * 20
        raise RuntimeError("not found")


def offline_setup():
    hs = FakeHubSpot()
    qualified = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == "Qualified")
    for name, domain, score in (("GTM Engineer - SampleCorp", "samplecorp.example", "96"),
                                ("AI Automation Specialist - Demo Systems", None, "70")):
        deal = hs.post("/crm/v3/objects/deals", {"properties": {
            "dealname": name, "pipeline": "default", "dealstage": qualified, "fit_score": score,
            "job_url": f"https://jobs.example/{score}", "description": f"{name}. Fully remote."}})
        if domain:
            company = hs.post("/crm/v3/objects/companies", {"properties": {"name": "SampleCorp", "domain": domain}})
            hs.put(f"/crm/v4/objects/deals/{deal['id']}/associations/default/companies/{company['id']}")

    def answer(system, prompt, schema):
        useful = "Revenue analytics" in prompt
        return {"brief_bullets": ["Made-up point one.", "Made-up point two.", "Made-up point three."],
                "cover_letter_angle": "Made-up angle.", "website_was_useful": useful,
                "suggested_contact_titles": ["Head of Growth", "Founder"]}

    return hs, FakeProvider(answer), OfflineHttp()


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Research qualified jobs in HubSpot.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="made-up data, fake AI and HubSpot")
    mode.add_argument("--preview", action="store_true", help="real data and AI, but write nothing")
    args = parser.parse_args(argv)

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    max_calls = int((config.get("llm") or {}).get("max_ai_calls_per_run", 40))
    if args.offline:
        hs, llm, http = offline_setup()
        label, write = "OFFLINE DEMO (made-up data, fake AI, fake HubSpot)", True
    else:
        load_dotenv(ROOT / ".env")
        hs, llm, http = HubSpotClient(), make_llm(config), Http()
        label = "PREVIEW (real data and AI, nothing written)" if args.preview else "LIVE (updates HubSpot)"
        write = not args.preview

    print(f"== Research jobs: {label}")
    report = Researcher(hs, llm, config, http=http, write=write).run(max_ai_calls=max_calls)
    lines = report.lines()
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## Research jobs: {label}\n\n```\n" + "\n".join(lines) + "\n```\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
