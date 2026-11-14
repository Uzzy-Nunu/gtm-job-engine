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

## Secrets
Listed in [PRD §16](PRD.md#16-configuration-and-secrets). Stored only in GitHub Secrets and Cloudflare secrets. Never paste them into code, chat or issues.

## Troubleshooting
_Filled in at M6._
