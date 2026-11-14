# Runbook

How to operate and troubleshoot GTM Job Engine. Sections are filled in as each milestone ships.

## Daily routine
_Filled in at M7._

## Running things by hand
- Rebuild CV templates: `python scripts/build_templates.py`
- Run tests: `python -m pytest`
- Render the made-up sample CV: `python scripts/render_sample_cv.py`

## HubSpot setup (Milestone 1)
Run from GitHub: **Actions > Setup HubSpot > Run workflow**.
- `plan` reads HubSpot and lists the changes. It writes nothing.
- `apply` makes the changes. It's safe to run again.
It stops on its own if the free plan's 10 custom-property limit would be exceeded or the pipeline already holds deals.

Locally (optional): put `HUBSPOT_TOKEN=...` in a `.env` file (git-ignored), then run `python scripts/setup_hubspot.py`.

### Review queue view
In HubSpot, **Deals > Review queue**: the Job Applications pipeline, filtered to *Ready for Review* and sorted by Fit Score (9 to 0). This is the daily review screen.

## Manual baseline (Milestone 2)
Time 5 real applications done fully by hand, split into 8 steps that match the pipeline:

| Column | Step |
|---|---|
| `find_min` | Find the role and check it is truly remote |
| `qualify_min` | Read the job description and judge fit |
| `research_min` | Research the company and the poster |
| `cv_min` | Tailor the CV |
| `cover_letter_min` | Write the cover letter |
| `outreach_min` | Draft the connection note and follow-up message |
| `apply_min` | Apply on the site and send the connection request |
| `tracking_min` | Log it in HubSpot |

- Blank sheet: `templates/baseline_timing_template.csv`. The filled sheet lives in `private/baseline_timing.csv`, which git ignores.
- Whole minutes. Use 0 for a step you skipped.
- Summary: `python scripts/baseline_summary.py`. Add `--write` to save the aggregates only (no company names) to `docs/baseline.md`.

## Adding a job by hand (Milestone 3)
- Practice run, nothing real changes: `python scripts/add_job.py --dry-run --demo`
- Real: `python scripts/add_job.py "<link>" --text-file post.txt` (needs `HUBSPOT_TOKEN`)
- A LinkedIn link with no text creates the deal flagged `NEEDS POST TEXT`. Paste the post text into the deal's **Deal description**, or submit the same link again with the text.
- Poster names come from the link and are marked "(unconfirmed)". Check them in HubSpot before reaching out.

## Secrets
Listed in [PRD §16](PRD.md#16-configuration-and-secrets). Stored only in GitHub Secrets and Cloudflare secrets. Never paste them into code, chat or issues.

## Troubleshooting
_Filled in at M6._
