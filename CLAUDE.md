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
- **Milestone 2 tools built (14 Nov 2026):** timing template `templates/baseline_timing_template.csv`, private copy `private/baseline_timing.csv` (git-ignored), `scripts/baseline_summary.py` (aggregates only, `--write` to `docs/baseline.md`). 30 tests passing. Peace is doing 5 timed applications by hand in Google Sheets (no Excel on this PC), then downloads the CSV to `private/`.
- **Milestone 2 complete (16 Nov 2026):** baseline from 1 timed application (Peace's decision, recorded in PRD): 120 minutes, published as aggregates in `docs/baseline.md`. The summary reads stopwatch formats and rejects minutes-turned-into-hours slips.
- **Milestone 3 part 1 complete (14 Nov 2026, committed):** `src/urls.py` (LinkedIn post parsing from the URL only, URL normalising, external job links), `src/intake.py` (dedupe, needs-post-text flag and later fill-in, company and poster upsert, associations via v4 default), `src/fake_hubspot.py` (in-memory HubSpot for dry runs and tests), `scripts/add_job.py` (`--dry-run --demo`). Shared link fixtures in `tests/fixtures/linkedin_urls.json` (the Worker must pass these too). `job_source` gained "Company Site" and "Other": Peace must re-run Setup HubSpot (apply) after the push. 62 tests passing.
- **Milestone 3 part 2 complete (17 Nov 2026, committed):** `src/sources/` (Greenhouse, Lever, Ashby, RemoteOK, Himalayas search, WWR RSS), `src/job_filter.py` (titles, remote, region, recency), `src/importer.py` (daily cap in Lagos time, isolated board failures), `scripts/import_jobs.py` (`--dry-run`, `--offline`), workflow `import-jobs.yml` (schedule gated by repo variable `ENABLE_SCHEDULED_IMPORT`). Live dry run 16 Nov: ~1,100 jobs read, 2 matched (most GTM roles are US-only). Greenhouse/Lever API hosts don't resolve on Peace's local network (DNS); they work from GitHub. 111 tests passing.
- **17 Nov 2026:** added adjacent titles (Growth Manager/Lead, Marketing Technology, MarTech, Lead/Demand Generation) and a generic RSS/Atom reader (`src/sources/feeds.py`, config `extra_feeds`) so Peace can add boards herself. 128 tests passing. Peace is sending a list of niche boards to evaluate (need: public feed/API, remote GTM roles, terms allow automated reading).
- **17 Nov 2026 (later):** reviewed Peace's 33 niche boards (`docs/job-boards.md`). Added Remotive (1 request per run) and Jobicy (geos anywhere + emea) as sources; Job Source gained "Remotive" and "Jobicy" (re-run Setup HubSpot apply). Http now spaces requests per site (1.5 s) and honours Retry-After after Himalayas rate-limited us; Himalayas uses 12 explicit searches, 1 page each. Live dry run: 5 boards, 4 new matches, 1 cross-board duplicate caught. 131 tests passing.
- Inclusively Remote added via `extra_feeds` (`link_from: guid`, `title_format: role`); deals without a company are named "Title - company TBC". Offline mode ignores `extra_feeds`. 133 tests passing; live dry run reads 6 boards cleanly.
- `explore_titles` list added (ranked after target/adjacent, labelled `Matched title list: explore` in the deal description, counted per list in the import summary, added to Himalayas searches; offline mode ignores it). Empty by default with commented suggestions. 137 tests passing.
- **17 Nov 2026 (master CV review):** Peace shared her master CV (read from her Downloads folder, never copied into the repo). Title lists rebuilt from its target titles: AI operations/automation family added to `target_titles`, GTM Strategist and Chief of Staff added to `adjacent_titles`, 7 `explore_titles`, QA/test automation and ML engineering added to exclusions, Himalayas searches updated (20 per run). Caps raised for 15 a day (`daily_import_cap: 100`, `daily_draft_cap: 20`); PRD §3 records the decision. Live dry run: 6 matches. 149 tests passing.
- **Decisions from the CV review (17 Nov 2026):** the no-country rule applies to the CV contact line only; employer and education entries keep their locations as written (PRD §12). Customer success and CX operations roles moved from `excluded_title_words` to `explore_titles` (10 explore titles, 23 Himalayas searches per run).
- **Next:** Peace re-runs Setup HubSpot (apply) to add the new Job Source options, runs Import jobs as a dry run on GitHub, then enables the schedule (`ENABLE_SCHEDULED_IMPORT=true`). Then M3 part 3 (Cloudflare Worker, paste form, bookmarklet). Target company list still to be supplied.
