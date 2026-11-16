"""Summarise the Milestone 2 manual baseline (PRD §3, §17).

Reads the private timing sheet (company names stay private) and prints the
average time per step and per application. With --write it saves only the
aggregate numbers to docs/baseline.md for the portfolio. No company or role
names are ever written to the repo. Samples smaller than 5 are allowed and
are labelled as small samples in the report.

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
RECOMMENDED_APPLICATIONS = 5  # fewer is allowed; the report says so

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


MAX_STEP_MINUTES = 8 * 60  # anything longer is almost certainly a typing slip


def parse_minutes(text: str) -> float:
    """Minutes from '12', '12.5', stopwatch 'm:ss' / 'm:ss.cc', or 'h:mm:ss'."""
    parts = text.strip().split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return float(parts[0]) + float(parts[1]) / 60
    if len(parts) == 3:
        return float(parts[0]) * 60 + float(parts[1]) + float(parts[2]) / 60
    raise ValueError(text)


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
                    minutes = parse_minutes(text)
                except ValueError:
                    raise SheetError(f"Row {line_no}: '{col}' should be minutes (e.g. 12 or 12:30), "
                                     f"got '{text}'")
                if minutes < 0:
                    raise SheetError(f"Row {line_no}: '{col}' cannot be negative")
                if minutes > MAX_STEP_MINUTES:
                    raise SheetError(
                        f"Row {line_no}: '{col}' reads as {minutes / 60:.1f} hours ('{text}'). "
                        "Google Sheets may have turned minutes into hours. Type it as plain "
                        "minutes, e.g. 30.")
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
    n = s["count"]
    lines = [
        "# Manual baseline (Milestone 2)",
        "",
        f"Time to complete one quality application **fully by hand**, measured over "
        f"{n} real application{'s' if n != 1 else ''}. Recorded {today:%d %b %Y}.",
        "This is the \"before\" number the automated system is compared against (PRD §3).",
        "",
    ]
    if n < RECOMMENDED_APPLICATIONS:
        lines += [
            f"> **Small sample:** based on {n} application{'s' if n != 1 else ''} "
            f"(the plan was {RECOMMENDED_APPLICATIONS}). Treat it as an indicative "
            "baseline, not an average.",
            "",
        ]
    lines += [
        "| | Minutes |",
        "|---|---|",
        f"| {'Average per application' if n > 1 else 'Total for the application'} | **{s['avg_total']:.0f}** |",
    ]
    if n > 1:
        lines += [
            f"| Median | {s['median_total']:.0f} |",
            f"| Fastest / slowest | {s['min_total']:.0f} / {s['max_total']:.0f} |",
        ]
    lines += [
        "",
        "## Where the time goes",
        "",
        f"| Step | {'Avg minutes' if n > 1 else 'Minutes'} | Share of time |",
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

    if args.write:
        OUTPUT.write_text(report, encoding="utf-8")
        print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
