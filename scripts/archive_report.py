"""Why are jobs archived? A read-only report on Archived deals.

  python scripts/archive_report.py            # real HubSpot (needs HUBSPOT_TOKEN)
  python scripts/archive_report.py --offline  # made-up deals

Reads each Archived deal's Job Analysis (written by the Qualify step) and counts:
  - archive reasons (not remote, region-restricted, excluded title, low score)
  - for low scores: the score spread and the average points per rubric part
  - region limits, seniority, title list and source
Prints job titles (public job-posting text), never company or poster details.
Nothing in HubSpot is changed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fake_hubspot import FakeHubSpot  # noqa: E402
from src.hubspot_client import HubSpotClient, HubSpotError, load_dotenv  # noqa: E402
from src.hubspot_schema import PIPELINE_LABEL  # noqa: E402

PART_NAMES = (("Remote", "remote"), ("Title", "title"), ("Skills", "skills"),
              ("Seniority", "seniority"), ("Salary", "salary"))


def category(reason: str) -> str:
    r = reason.lower()
    if r.startswith("not remote"):
        return "Not remote (on-site or hybrid)"
    if r.startswith("remote only for"):
        return "Remote only in a region you can't work from"
    if r.startswith("title contains"):
        return "Excluded word in the title"
    if r.startswith("fit score"):
        return "Fit score below the threshold"
    return "Other (archived by hand or before scoring)"


def parse(analysis: str) -> dict:
    out = {"reason": "", "score": None, "parts": {}, "remote": "", "seniority": "", "title_list": ""}
    for line in (analysis or "").splitlines():
        if line.startswith("Reason:"):
            out["reason"] = line[len("Reason:"):].strip()
        elif line.startswith("Fit score:"):
            m = re.match(r"Fit score: (\d+)", line)
            out["score"] = int(m.group(1)) if m else None
        elif line.startswith("Score:"):
            for chunk in line[len("Score:"):].split(" | "):
                m = re.match(r"\s*(.*) \+(\d+)$", chunk)
                if not m:
                    continue
                label, pts = m.group(1), int(m.group(2))
                key = next((k for name, k in PART_NAMES if label.startswith(name) or
                            (k == "remote" and "emote" in label) or (k == "salary" and "alary" in label)), None)
                if key:
                    out["parts"][key] = pts
                if label.startswith("Title"):
                    m2 = re.search(r"your (\w+) list", label)
                    out["title_list"] = m2.group(1) if m2 else "none"
        elif line.startswith("Seniority:"):
            out["seniority"] = line.split("|")[0].split(":", 1)[1].strip()
            m = re.search(r"Remote: (.*)$", line)
            out["remote"] = m.group(1).strip() if m else ""
    return out


def archived_deals(hs) -> list[dict]:
    pipe = next(p for p in hs.get("/crm/v3/pipelines/deals")["results"] if p.get("label") == PIPELINE_LABEL)
    stage = {s["label"]: s["id"] for s in pipe["stages"]}
    out, after = [], None
    while True:
        body = {"filterGroups": [{"filters": [
                    {"propertyName": "pipeline", "operator": "EQ", "value": pipe["id"]},
                    {"propertyName": "dealstage", "operator": "EQ", "value": stage["Archived"]}]}],
                "properties": ["dealname", "job_analysis", "job_source"], "limit": 100,
                "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}]}
        if after:
            body["after"] = after
        page = hs.post("/crm/v3/objects/deals/search", body) or {}
        out += page.get("results", [])
        after = ((page.get("paging") or {}).get("next") or {}).get("after")
        if not after:
            return out


def report(deals: list[dict]) -> list[str]:
    rows = []
    for d in deals:
        p = d.get("properties", {})
        info = parse(p.get("job_analysis") or "")
        info["title"] = (p.get("dealname") or "").split(" - ")[0].strip()
        info["source"] = p.get("job_source") or "unknown"
        rows.append(info)

    lines = [f"Archived deals: {len(rows)}", "", "WHY THEY WERE ARCHIVED"]
    cats = Counter(category(r["reason"]) for r in rows)
    lines += [f"- {c}: {n}" for c, n in cats.most_common()]

    low = [r for r in rows if category(r["reason"]) == "Fit score below the threshold"]
    if low:
        scores = sorted(r["score"] for r in low if r["score"] is not None)
        bands = Counter(f"{(s // 10) * 10}-{(s // 10) * 10 + 9}" for s in scores)
        lines += ["", "LOW-SCORE JOBS: SCORE SPREAD"] + [f"- {b}: {n}" for b, n in sorted(bands.items())]
        sums, counts = defaultdict(int), defaultdict(int)
        for r in low:
            for k, v in r["parts"].items():
                sums[k] += v
                counts[k] += 1
        lines += ["", "LOW-SCORE JOBS: AVERAGE POINTS PER PART (max: remote 30, title 25, skills 20, "
                  "seniority 15, salary 10)"]
        lines += [f"- {name}: {sums[k] / counts[k]:.1f}" for name, k in PART_NAMES if counts[k]]
        lines += ["", "LOW-SCORE JOBS: SENIORITY"] + \
                 [f"- {s or 'unknown'}: {n}" for s, n in Counter(r["seniority"] for r in low).most_common()]
        lines += ["", "LOW-SCORE JOBS: TITLE LIST"] + \
                 [f"- {t or 'unknown'}: {n}" for t, n in Counter(r["title_list"] for r in low).most_common()]

    region = [r for r in rows if category(r["reason"]).startswith("Remote only")]
    if region:
        lines += ["", "REGION LIMITS"] + [f"- {k}: {n}" for k, n in Counter(
            r["reason"][len("Remote only for "):].split(", which")[0] for r in region).most_common()]

    lines += ["", "BY SOURCE"] + [f"- {s}: {n}" for s, n in Counter(r["source"] for r in rows).most_common()]
    lines += ["", "EACH JOB (title | source | score | reason)"]
    lines += [f"- {r['title'][:70]} | {r['source']} | {r['score'] if r['score'] is not None else '-'} | "
              f"{r['reason'][:90] or 'no reason recorded'}" for r in rows]
    return lines


def offline_hubspot() -> FakeHubSpot:
    hs = FakeHubSpot()
    archived = next(s["id"] for s in hs.pipeline["stages"] if s["label"] == "Archived")
    samples = [
        ("Growth Manager - Demo", "Himalayas", "Fit score: 54/100 (threshold 70) -> Archived\n"
         "Reason: Fit score 54 is below the threshold of 70.\n"
         "Score: Remote in an eligible region (EMEA) +20 | Title matches your adjacent list +15 | "
         "Skills and tools overlap (12/20) +12 | Seniority: Unclear +7 | No salary listed +0\n"
         "Seniority: Unclear | Salary: not listed | Remote: Region (EMEA)"),
        ("RevOps Manager - Demo", "Remotive", "Fit score: 0/100 (threshold 70) -> Archived\n"
         "Reason: Remote only for USA, which isn't open to you.\nScore: Hard filter +0\n"
         "Seniority: Senior | Salary: not listed | Remote: Country-restricted (USA)"),
    ]
    for name, source, analysis in samples:
        hs.post("/crm/v3/objects/deals", {"properties": {"dealname": name, "pipeline": "default",
                                                         "dealstage": archived, "job_source": source,
                                                         "job_analysis": analysis}})
    return hs


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Why are jobs archived?")
    parser.add_argument("--offline", action="store_true", help="made-up deals")
    args = parser.parse_args(argv)
    if args.offline:
        hs = offline_hubspot()
    else:
        load_dotenv(ROOT / ".env")
        hs = HubSpotClient()
    try:
        lines = report(archived_deals(hs))
    except HubSpotError as e:
        print(f"! Couldn't read HubSpot: {e}")
        return 1
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Archive report\n\n```\n" + "\n".join(lines) + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
