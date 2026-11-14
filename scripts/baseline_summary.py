"""Summarise the Milestone 2 manual baseline (PRD §3, §17).

Reads the private timing sheet (company names stay private) and prints the
average time per step and per application. With --write it saves only the
aggregate numbers to docs/baseline.md for the portfolio. No company or role
names are ever written to the repo.

Usage:
  python scripts/baseline_summary.py                      # reads private/baseline_timing.csv
  python scripts/baseline_summary.py --write              # also writes docs/baseline.md
  python scripts/baseline_summary.py path/to/sheet.csv
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHEET = ROOT / "private" / "baseline_timing.csv"
OUTPUT = ROOT / "docs" / "baseline.md"
REQUIRED_APPLICATIONS = 5

# Column -> plain-English step name, in pipeline order (PRD §8).
STEPS = {
    "find_min": "Find the role and check it is truly remote",
    "qualify_min": "Read the job description and judge fit",
    "research_min": "Research the company and the poster",
    "cv_min": "Tailor the CV",
    "cover_letter_min": "Write the cover letter",
    "outreach_min": "Draft connection note and follow-up message",
    "apply_min": "Apply on the site and send the connection request",
    "tracking_min": "Log it in HubSpot",
}


class SheetError(ValueError):
    pass


def load_rows(path: Path) -> list[dict[str, float]]:
    """Return one {step: minutes} dict per filled-in application row."""
    if not path.exists():
        raise SheetError(f"Sheet not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in STEPS if c not in (reader.fieldnames or [])]
        if missing:
            raise SheetError(f"Missing columns: {', '.join(missing)}")
        rows = []
        for line_no, raw in enumerate(reader, start=2):
            values = {c: (raw.get(c) or "").strip() for c in STEPS}
            if not any(values.values()):
                continue  # blank line
            row = {}
            for col, text in values.items():
                if text == "":
                    raise SheetError(f"Row {line_no}: '{col}' is empty (use 0 if no time)")
                try:
                    minutes = float(text)
                except ValueError:
                    raise SheetError(f"Row {line_no}: '{col}' should be a number of minutes, got '{text}'")
                if minutes < 0:
                    raise SheetError(f"Row {line_no}: '{col}' cannot be negative")
                row[col] = minutes
            rows.append(row)
    if not rows:
        raise SheetError("The sheet has no filled-in applications yet.")
    return rows


def summarise(rows: list[dict[str, float]]) -> dict:
    totals = [sum(r.values()) for r in rows]
    grand = sum(totals)
    steps = {}
    for col, name in STEPS.items():
        values = [r[col] for r in rows]
        steps[col] = {
            "name": name,
            "avg": statistics.mean(values),
            "share": (sum(values) / grand * 100) if grand else 0.0,
        }
    return {
        "count": len(rows),
        "avg_total": statistics.mean(totals),
        "median_total": statistics.median(totals),
        "min_total": min(totals),
        "max_total": max(totals),
        "steps": steps,
    }


def to_markdown(s: dict, today: date | None = None) -> str:
    today = today or date.today()
    lines = [
        "# Manual baseline (Milestone 2)",
        "",
        f"Time to complete one quality application **fully by hand**, measured over "
        f"{s['count']} real applications. Recorded {today:%d %b %Y}.",
        "This is the \"before\" number the automated system is compared against (PRD §3).",
        "",
        "| | Minutes |",
        "|---|---|",
        f"| Average per application | **{s['avg_total']:.0f}** |",
        f"| Median | {s['median_total']:.0f} |",
        f"| Fastest / slowest | {s['min_total']:.0f} / {s['max_total']:.0f} |",
        "",
        "## Where the time goes",
        "",
        "| Step | Avg minutes | Share of time |",
        "|---|---|---|",
    ]
    for step in s["steps"].values():
        lines.append(f"| {step['name']} | {step['avg']:.1f} | {step['share']:.0f}% |")
    lines += [
        "",
        f"At this pace, 5 applications a day would take about "
        f"**{s['avg_total'] * 5 / 60:.1f} hours**.",
        "",
        "_Aggregates only. The raw sheet (with company names) is kept private._",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Summarise the manual baseline.")
    parser.add_argument("sheet", nargs="?", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--write", action="store_true",
                        help="save aggregates to docs/baseline.md")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        rows = load_rows(args.sheet)
    except SheetError as e:
        print("ERROR:", e)
        return 1

    summary = summarise(rows)
    report = to_markdown(summary)
    print(report)

    if summary["count"] < REQUIRED_APPLICATIONS:
        print(f"NOTE: {summary['count']} of {REQUIRED_APPLICATIONS} applications logged. "
              "Milestone 2 needs 5.")
    if args.write:
        if summary["count"] < REQUIRED_APPLICATIONS:
            print("Not writing docs/baseline.md until all 5 are logged.")
            return 1
        OUTPUT.write_text(report, encoding="utf-8")
        print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
