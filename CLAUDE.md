# CLAUDE.md: GTM Job Engine

Instructions for Claude Code working in this repository. Read `docs/PRD.md` before writing any code. It is the source of truth for scope, data model, requirements and milestones.

## About the owner
- Peace George, a GTM engineer and growth strategist. She's tech-savvy but new to coding: **explain each step in plain, simple language** and say what she needs to click or do.
- Windows machine. She uses GitHub Desktop to commit and push. Claude can also commit and push using her local git login when she asks.
- This repo is **public** and doubles as her portfolio, so code, commit messages and docs should be clean and professional.

## What we're building
A semi-automated job-search system: intake of remote GTM roles (capture bookmarklet, paste-a-link form, job board feeds) → AI qualification and fit scoring → company research → tailored ATS CV, cover letter and outreach drafts → human review and approval in HubSpot. See `docs/PRD.md`.

**Stack:** Python 3.12, HubSpot free CRM (API via Service Key; legacy private apps can no longer be created), Gemini API (free tier in Phase 1; provider switchable to Claude in config), Cloudflare Worker (capture endpoint and paste form), GitHub Actions (schedules), python-docx (CV rendering).

## Non-negotiable rules
1. **Never commit personal data or secrets.** No CV content, contact details, API keys or tokens in the repo. The master CV lives outside the repo and goes in the GitHub Secret `MASTER_CV`. Keys go in GitHub Secrets and Cloudflare secrets. Keep `.gitignore` strict (`.env`, `*.local.*`, `private/`, `master_cv*`, output files).
2. **No LinkedIn automation.** The system never fetches, scrapes or logs into LinkedIn. Poster details are parsed from the post URL. Job text comes from Peace (paste or highlight) or from external job pages linked in the post.
3. **A human approves anything irreversible.** No auto-apply, no auto-send.
4. **Truth only in CV generation.** The AI may select and reword facts from the master CV but never invent skills, tools, titles, dates or results. Include the truth-check pass.
5. **Data minimisation for the free Gemini tier.** Never send contact details (Peace's or third parties') to the AI. Redact emails, phones and profile URLs from job text before AI calls. Send only the master CV sections each prompt needs.
6. **CV output rules:** single column, plain-text safe, standard capitalised headings, hyphen bullets, `Mon YYYY - Mon YYYY` dates, no tables, images, headers or footers, 2 pages max, location shown as `Remote` (no country).
7. **Re-runs must be safe** (no duplicates), errors must be loud (alerts), and there must be a dry-run mode using made-up test data.

## How to work
- Follow the milestone order in PRD §17 (M0 → M9). Finish and test one milestone before starting the next.
- Small, focused commits with clear messages.
- Test with sample data in `tests/fixtures/` before touching real HubSpot data.
- When Peace needs to set something up (HubSpot Service Key, GitHub Secrets, Cloudflare), give numbered click-by-click steps. Ask her to paste keys into GitHub or Cloudflare directly, never into chat or code.
- Keep `docs/PRD.md` updated when decisions change, and keep `README.md` written as a portfolio case study.

## Current status (13 Nov 2026)
- PRD v1.0 is complete (`docs/PRD.md`).
- Master CV is written and kept outside the repo.
- Accounts: GitHub, HubSpot (free), Cloudflare created. Gemini API key from Google AI Studio still to be created. Email finding (Hunter) is deferred.
- **Milestone 0 complete (approved 13 Nov 2026, paste test passed):** repo structure, `.gitignore`, `config.yaml`, ATS templates (`scripts/build_templates.py` → `templates/`), renderer `src/render_docx.py`, tests in `tests/` (12 passing), README and runbook skeletons. Target company list still to be supplied by Peace.
- Local Python env lives outside OneDrive at `C:\Users\KRITEX\.venvs\gtm-job-engine` (local Python is 3.14; code targets 3.12+).
- **Milestone 1 complete (14 Nov 2026):** Service Key created and stored as `HUBSPOT_TOKEN` GitHub Secret. Setup HubSpot workflow applied: "Job Applications" pipeline (11 stages) and 9 custom deal properties live. 8 old marketing custom properties were archived (restorable until about 12 Feb 2027) to fit the free plan's limit of 10. "Review queue" deal view saved (stage = Ready for Review, sorted by Fit Score high to low). Workflows use actions/checkout@v5 and setup-python@v6.
- **Next:** Milestone 2, the manual baseline: Peace does 5 applications fully by hand and times them. Target company list still to be supplied.
