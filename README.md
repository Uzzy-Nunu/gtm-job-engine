# GTM Job Engine

**A human-in-the-loop system that finds remote Go-to-Market (GTM) roles, scores fit, researches the company and drafts tailored, ATS-friendly applications for review in HubSpot.**

> Status: 🚧 In build. Milestone 0 (foundations) complete. See [roadmap](#roadmap).

---

## The problem

Quality job applications are slow. Each one means finding roles that are *truly* remote worldwide, judging fit, researching the company and the person hiring, and tailoring a CV so AI screening ranks it highly. Done by hand, volume suffers. Sending generic applications at scale doesn't work either: they score poorly and get ignored.

## The approach

Automate the repetitive research and drafting. Keep a human in charge of every irreversible step.

```
Capture / paste link / job boards
        -> HubSpot deal (New)
        -> AI qualify + fit score
        -> company research
        -> tailored CV, cover letter, outreach drafts
        -> human review and approval in HubSpot
        -> human applies and sends
```

**Target:** 5 high-quality applications a day in about 45 minutes of human time, scaling to 15 a day once the system is proven.

## Design decisions

| Decision | Why |
|---|---|
| **Human approves anything irreversible** | No auto-apply, no auto-send. The system drafts; a person decides. |
| **No LinkedIn automation** | Respects platform rules and protects the account. Poster details are parsed from the post URL itself; LinkedIn pages are never fetched. |
| **Truth-only CV tailoring** | The AI may only select and reword facts from a master CV, followed by a separate truth-check pass. |
| **Data minimisation** | Contact details are never sent to the AI. Emails, phones and profile URLs are redacted from job text first. |
| **HubSpot as the single source of truth** | Every job is a deal; every module moves it by changing its stage. The CRM doubles as the review queue. |
| **ATS-safe output** | Single column, standard headings, hyphen bullets, no tables, images, headers or footers. Automated tests enforce it. |
| **Safe re-runs, loud failures, dry-run mode** | Unique keys prevent duplicates; errors alert; a dry run uses made-up data only. |

## Architecture

_Diagram coming in Milestone 8._ Full detail in [docs/PRD.md](docs/PRD.md#8-system-architecture).

## Stack

Python 3.12 · HubSpot free CRM (private app API) · Gemini API (free tier, switchable to Claude) · Cloudflare Workers · GitHub Actions · python-docx

## Repository layout

```
config.yaml          roles, rubric, caps, sources, model choice (no personal data)
docs/                PRD and runbook
prompts/             version-controlled AI prompts
src/                 pipeline modules (intake, qualify, research, draft, render, digest)
templates/           ATS-safe CV and cover letter templates (.docx)
scripts/             setup and helper scripts
worker/              Cloudflare Worker: capture endpoint and paste-a-link form
apps_script/         Gmail job-alert reader (later)
tests/fixtures/      made-up sample data only
.github/workflows/   schedules and CI
```

## Roadmap

| # | Milestone | Status |
|---|---|---|
| M0 | Foundations: repo, config, rubric, ATS CV template | ✅ Done |
| M1 | HubSpot pipeline and properties setup | ⏳ Next |
| M2 | Manual baseline (5 applications timed by hand) | |
| M3 | Intake: job boards, capture bookmarklet, paste-a-link form | |
| M4 | Qualify and research | |
| M5 | Draft: tailored CV, cover letter, messages, truth check | |
| M6 | Operations: schedules, digest, alerts, dry run | |
| M7 | Go live | |
| M8 | Portfolio write-up | |
| M9 | Scale to 15 a day | |

## Results

_To be filled with real measured data after go-live. No invented numbers._

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python scripts/build_templates.py
python -m pytest
python scripts/render_sample_cv.py   # writes output/sample_cv.docx from made-up data
```

## Privacy

This repository contains no personal data. The master CV and all keys live in GitHub Secrets and Cloudflare secrets. Test fixtures use made-up people and `example.com` addresses.

---

Built by Peace George, GTM engineer and growth strategist.
