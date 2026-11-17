# GTM Job Engine

**A human-in-the-loop system that finds remote Go-to-Market (GTM) roles, scores fit, researches the company and drafts tailored, ATS-friendly applications for review in HubSpot.**

> Status: 🚧 In build. Milestones 0-4 complete (foundations, HubSpot, baseline, intake, AI qualification and research); drafting (M5) next. See [roadmap](#roadmap).

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
| **AI reads, code decides** | The AI extracts facts and judges skills overlap; hard filters and the fit-score rubric are plain code, so every score has a readable breakdown. Contact details are redacted before any AI call, only the skills and tools part of the CV is ever sent, and preview modes show results before anything is written. |
| **Capture without automation** | A Cloudflare Worker serves a phone-friendly paste form and a one-click bookmarklet. Poster details come from the post URL itself, and the access key never sits in a link or bookmark. One post can carry two LinkedIn IDs, so repeats are also matched by poster and text. |
| **Widen the funnel, not the noise** | Eight job sources (public APIs and RSS, never scraped pages) pass title, remote-eligibility and recency filters before anything reaches the CRM. New boards and exploratory titles are config edits, not code changes. |
| **Lean CRM model** | HubSpot's free CRM allows 10 custom properties, so the model uses 9 and keeps everything else in built-in fields, notes and attachments. Setup is idempotent and checks the limit before writing. |
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
| M1 | HubSpot pipeline and properties setup | ✅ Done |
| M2 | Manual baseline (timed by hand) | ✅ Done (1 application) |
| M3 | Intake: job boards, capture bookmarklet, paste-a-link form | ✅ Done |
| M4 | Qualify and research | ✅ Done |
| M5 | Draft: tailored CV, cover letter, messages, truth check | ⏳ Next |
| M6 | Operations: schedules, digest, alerts, dry run | |
| M7 | Go live | |
| M8 | Portfolio write-up | |
| M9 | Scale to 15 a day | |

## Results

**Baseline (before automation):** one quality application done fully by hand took **120 minutes**. About 75% of that went on research, CV tailoring, the cover letter and outreach messages, which are the steps the system drafts. At that pace, 5 applications a day would take about 10 hours. Details: [docs/baseline.md](docs/baseline.md) (small sample: 1 application).

_After-launch results will be added from real measured data. No invented numbers._

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
