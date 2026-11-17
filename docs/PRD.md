# PRD: GTM Job Engine

**Owner:** Peace George
**Status:** Draft v1.0
**Last updated:** 13 Nov 2026
**Repository:** `gtm-job-engine` (public, with no personal data committed)

---

## 1. Summary

GTM Job Engine is a semi-automated system that finds remote GTM engineering roles, scores how well each one fits, researches the company, and drafts a tailored ATS-friendly CV, cover letter and outreach messages. Everything lands in HubSpot for human review. Nothing is submitted or sent without Peace's approval.

**North-star goal:** start with 5 high-quality, well-targeted job applications per day in about 45 minutes of human time, then scale to 15 per day once the system is proven (see §3).

**Secondary goal:** a public, well-documented portfolio project that shows GTM engineering skills (CRM data modelling, data sourcing, AI workflows, automation, human-in-the-loop design).

---

## 2. Problem

Quality applications are slow to produce. For each role you have to:
1. Find roles that are **truly remote worldwide**, not "remote, US only".
2. Understand the job description and judge fit.
3. Research the company and the person who posted the role.
4. Tailor the CV and cover letter to the job description's keywords so AI screening ranks them highly.
5. Track everything and follow up on time.

Done by hand, this limits volume, and quality drops under time pressure. Sending mass generic applications doesn't work either: they score poorly in AI screening and get ignored.

---

## 3. Goals and success metrics

| Metric | Target | How it's measured |
|---|---|---|
| Quality applications sent | **Phase 1:** 5 per weekday. **Phase 2:** 15 per weekday, once the system is proven (see scale-up criteria below) | Deals moved to `Applied` per day |
| Human time per application | 50%+ less than the manual baseline | Manual baseline timed in Milestone 2, compared with time logged after launch |
| Qualified rate | 20–40% of captured jobs | `Qualified` ÷ `New` |
| Keyword coverage on tailored CVs | ≥ 80% of the job's key requirements that are truthfully matched | `keyword_coverage` property |
| Reply rate (recruiter, poster or hiring manager) | Tracked, with no target in v1 | Deals with a logged reply |
| Interview rate | Tracked | Deals reaching `Interviewing` |
| Cost | $0 in Phase 1 (free tiers only). Under about $25 a month in Phase 2 once AI moves to a paid tier | Tool billing |

All portfolio results must come from real measured data. No invented numbers.

### Scale-up criteria (Phase 1 → Phase 2)
Move from 5 to 15 applications a day only when all of these are true:
- M7 is complete: 5 applications a day for at least 5 working days in a row.
- At least 90% of drafts pass the truth check with no unsupported claims.
- Peace's edit time per application is stable and low enough that 15 a day fits the time she has.
- There have been no unhandled pipeline errors in the past week.
- There are enough qualified jobs coming in (at least 25 per day reaching `Qualified`) to keep quality high at 15 applications a day.

To scale up, raise `daily_draft_cap` and `daily_import_cap` in `config.yaml` (see §16), and move the AI to a paid tier if free-tier limits get in the way (§11.1). No code changes are needed.

**Decision (17 Nov 2026): the caps are set for 15 a day from the start** (`daily_import_cap: 100`, `daily_draft_cap: 20`), so the system doesn't need revisiting after launch. The scale-up criteria above become **quality checks to monitor** rather than gates. In the first weeks, watch the truth-check pass rate and Peace's edit time. If drafts need too much editing, lower `daily_draft_cap` (a config change). The practical limit is job supply: about 40+ incoming jobs a day are needed at a 20–40% qualify rate, which depends on LinkedIn captures and the target company list as much as on job boards.

---

## 4. Users

| User | Role |
|---|---|
| **Operator (Peace)** | Captures LinkedIn posts, reviews and edits drafts, approves, applies, sends connection requests and messages |
| **System** | Pulls jobs in, qualifies them, researches, drafts, organises, reminds |

---

## 5. Scope

### In scope (v1)
- Job intake from: (a) a one-click LinkedIn capture button, (b) a **paste-a-link form** where Peace pastes a LinkedIn post URL (works on phone or desktop), and the system records the job requirements and the poster's details, (c) public job-board feeds, (d) LinkedIn job-alert emails (P1).
- Removing duplicates, and recording the company and the job poster in HubSpot.
- AI extraction of job details and a fit score with reasons.
- A company research brief, plus suggested hiring-manager titles to look up by hand.
- Tailored CV (.docx), cover letter (.docx), LinkedIn connection note and follow-up message.
- A HubSpot pipeline used as the review and approval queue.
- A daily digest email and follow-up reminders.
- Error alerts, logging, and a dry-run test mode.

### Out of scope (v1)
- **Automated LinkedIn browsing, scraping, messaging or connecting.** LinkedIn stays a human-only step (platform rules and account safety).
- **Auto-applying** to jobs.
- **Automatic sending** of any email or message.
- **Email finding** (for example Hunter). Peace finds contact emails by hand when needed. *(See §19, future work.)*
- Gmail API integration (v1 uses HubSpot and the digest email instead).

---

## 6. Guiding principles (non-negotiable)

1. **A human approves anything irreversible.** Applying, connecting and messaging are always done by Peace.
2. **Truth only.** The AI may select, reorder and reword facts from the master CV. It must never invent experience, skills, tools, titles, dates or results.
3. **Respect platform rules.** No automation runs against Peace's LinkedIn account.
4. **Privacy.**
   - No personal data is committed to the public repo.
   - Only the minimum personal data needed is sent to the AI. Phase 1 uses the free Gemini tier as an accepted risk (see §11.1).
   - Contact details (Peace's and third parties') are never sent to the AI. Names and contact lines are inserted into templates by the code.
5. **One source of truth.** HubSpot holds the state of every job. Every module moves a record by changing its stage.
6. **No duplicates.** Each job has a unique key, so it's processed once.
7. **Score before you spend.** Only qualified jobs get drafted.
8. **Fail loudly.** Errors trigger an alert and never fail silently.

---

## 7. Daily operator workflow (target: about 45 minutes)

| Time | Step |
|---|---|
| Automatic, overnight and morning | System pulls new jobs, qualifies, researches and drafts |
| 07:30 Lagos | Digest email arrives: N jobs ready for review, overdue follow-ups |
| ~10 min | Browse LinkedIn hiring posts and click **Capture** on good ones |
| ~20 min | Open the HubSpot **Ready for Review** board, read the fit reasons, open and edit the CV and cover letter, approve or archive |
| ~15 min | For approved jobs: apply on the company site, send a LinkedIn connection request to the poster, send the follow-up message, then move the deal to `Applied` |

---

## 8. System architecture

```
                         ┌──────────────────────────┐
 LinkedIn post (Peace) ─►│ Capture bookmarklet  or   │
 (desktop or phone)      │ Paste-a-link form (/add)  │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │ Cloudflare Worker         │  always-on endpoint
                         │ /capture                  │  (validates secret)
                         └────────────┬─────────────┘
                                      │ creates deal (stage: New)
 Job boards (Greenhouse, Lever,       ▼
 Ashby, RemoteOK, Himalayas, ──► ┌──────────────────────────┐
 We Work Remotely RSS)           │        HUBSPOT            │◄── Peace reviews,
 LinkedIn job-alert emails ────► │ Deals · Companies ·       │    edits, approves
 (Google Apps Script, P1)        │ Contacts · Files          │
                                 └────────────┬─────────────┘
                                              ▲│
                      GitHub Actions (schedule)│▼
                         ┌──────────────────────────────────┐
                         │ Python pipeline                   │
                         │ intake → qualify → research →     │
                         │ draft → digest / nudges           │
                         │        │                          │
                         │        ▼                          │
                         │  LLM provider (Gemini or Claude)  │
                         └──────────────────────────────────┘
```

### Components

| Component | Technology | Purpose |
|---|---|---|
| CRM / database | HubSpot (free CRM) | Source of truth, review queue, files |
| Pipeline code | Python 3.12 | Intake, qualify, research, draft, digest |
| Scheduler | GitHub Actions (cron and manual trigger) | Runs the pipeline on a schedule |
| Capture endpoint | Cloudflare Worker (free) | Receives bookmarklet clicks around the clock |
| Job-alert reader (P1) | Google Apps Script | Reads a Gmail label and posts to the Worker |
| AI | Gemini API or Claude API (configurable) | Extraction, scoring, research summary, drafting |
| Documents | python-docx | ATS-safe .docx CV and cover letter |
| Secrets | GitHub Secrets, Cloudflare secrets | API keys and master CV |

---

## 9. Data model (HubSpot)

### 9.1 Pipeline: `Job Applications`
The free CRM includes **one** deal pipeline. The setup script renames and reconfigures the default pipeline.

| Stage | Meaning | Who moves it |
|---|---|---|
| `New` | Captured or imported, not yet processed | System |
| `Qualified` | Fit score ≥ threshold and passes the hard filters | System |
| `Researched` | Company brief and suggested contacts added | System |
| `Ready for Review` | CV, cover letter and messages drafted | System |
| `Approved` | Peace approved the drafts | Peace |
| `Applied` | Application submitted | Peace |
| `Followed Up` | Follow-up sent | Peace |
| `Interviewing` | Interview stage | Peace |
| `Offer` | Offer received | Peace |
| `Rejected` | Closed by the company | Peace |
| `Archived` | Low fit, duplicate, expired or skipped | System or Peace |

### 9.2 Deal properties (custom)

**Decision (M1, 13 Nov 2026):** HubSpot's free CRM allows **10 custom properties in total** across the account (HubSpot product catalog, Free tools). The model is therefore lean: 9 custom deal properties, with 1 spare. Everything else uses built-in fields, associations and notes. The setup script checks the limit before writing anything. The definitions live in `src/hubspot_schema.py`.

| Label | Internal name | Type | Set by |
|---|---|---|---|
| Job URL | `job_url` | Single-line text (unique key). For LinkedIn posts, the normalised post URL, which contains the post ID | Intake |
| Job Source | `job_source` | Dropdown: LinkedIn Post / LinkedIn Alert / Greenhouse / Lever / Ashby / RemoteOK / Himalayas / WWR | Intake |
| Apply URL | `apply_url` | Single-line text | Qualify |
| Remote Scope | `remote_scope` | Dropdown: Worldwide / Region / Country-restricted / Unclear / Not remote | Qualify |
| Fit Score | `fit_score` | Number (0–100) | Qualify |
| Keyword Coverage % | `keyword_coverage` | Number | Draft |
| Job Analysis | `job_analysis` | Multi-line text: fit reasons, seniority, salary, eligible regions, required skills, tools, missing keywords, suggested contact titles | Qualify, Research, Draft |
| Pipeline Error | `pipeline_error` | Multi-line text. `NEEDS POST TEXT` at the start replaces the old checkbox | System |
| Applied Date | `applied_date` | Date (stage-entered dates need a Professional plan) | Peace |

**Where the other planned fields went:**

| Planned field | Now stored in |
|---|---|
| Job title, company | Deal name `<Job Title> - <Company>` and the associated company |
| Raw job text | Built-in deal **Deal description** (Peace pastes missing post text here) |
| LinkedIn post ID | Inside `job_url` |
| Needs post text | `pipeline_error` = `NEEDS POST TEXT ...` |
| Eligible regions, seniority, salary, skills, tools, fit reasons, missing keywords, suggested contact titles | `job_analysis` |
| Company brief | Built-in company **Description**, plus a note on the deal |
| CV and cover letter files | Attachments on a deal note (shown in the deal's Attachments panel) |
| Connection note, follow-up message | A "Drafts" note on the deal |
| Minutes spent | Not stored in HubSpot. Time is logged in the M2 baseline sheet |

### 9.3 Company
Uses default properties: name, domain, website, description (company brief). Linked to the deal.

### 9.4 Contact (job poster)
Default name properties plus the built-in **LinkedIn URL** property (`hs_linkedin_url`) for the poster's profile link. No custom contact properties (the old `pipeline_role` field is dropped: contacts the system creates are always posters, and hiring managers are added by hand). Linked to the deal and the company.

### 9.5 Authentication
HubSpot stopped allowing new legacy private apps on 26 Oct 2026. The system uses a **Service Key** (Development > Keys > Service keys), sent as a Bearer token and stored as the `HUBSPOT_TOKEN` secret. Minimum scopes: deal, contact and company object read/write, and deal and contact property-settings read/write. `files.write` is added in M5.

---

## 10. Functional requirements

Priority: **P0** = required for launch, **P1** = soon after launch, **P2** = nice to have.

### 10.1 Intake

| ID | Requirement | Priority |
|---|---|---|
| IN-1 | **Capture bookmarklet:** takes the current page URL and any text Peace has highlighted and opens the Worker's `/add` form with both filled in (passed in the URL `#fragment`, which is never sent to a server). Peace clicks Save; the form sends it to `/capture` with the shared secret. **Decision (17 Nov 2026):** the bookmarklet holds no secret. The access key is typed once into the form and kept in that browser, so it never appears in a bookmark or link. | P0 |
| IN-1b | **Paste-a-link form:** a simple, mobile-friendly page served by the Worker (`/add`, protected by the shared secret). Fields: **LinkedIn post URL** (required), **post text** (optional but recommended: Peace copies and pastes the post text), and notes. Built so Peace can add a job from her phone in under 30 seconds, for example right after tapping "Copy link to post" in the LinkedIn app. | P0 |
| IN-1c | **Poster details from the URL:** LinkedIn post URLs usually contain the author's profile name and a unique post ID (for example `linkedin.com/posts/jane-doe-123_hiring-gtm-activity-7390000000000000000-AbCd`). The Worker reads these directly from the URL **without visiting LinkedIn**. It stores the poster's profile link (`linkedin.com/in/jane-doe-123`), a best-guess display name (shown as "unconfirmed" until checked), and the post ID, which is the duplicate-check key. It also accepts `/feed/update/urn:li:activity:…` URLs, which give the post ID but no author. | P0 |
| IN-1d | **Job requirements from the post text:** when post text is supplied (by the paste form or highlighted with the bookmarklet), the Qualify step extracts the requirements, skills, tools, remote scope and any external job link from it. | P0 |
| IN-1e | **Follow the real job link:** if the post text contains a link to the job on a company site or ATS (Greenhouse, Lever, Ashby, Workable and so on), the system fetches that page for the full job description and apply URL. LinkedIn pages themselves are never fetched. | P0 |
| IN-1f | **Missing text fallback:** if only a URL is submitted with no text and no external job link, the deal is created with the poster's details and flagged **"Needs post text"**. The daily digest lists these so Peace can paste the text in HubSpot (one field) and the pipeline picks them up on the next run. | P0 |
| IN-2 | **Worker:** validates the secret, normalises the URL (removes tracking parameters), checks HubSpot for an existing post ID or `job_url`, creates the deal (`New`, source = LinkedIn Post) and the poster contact, and returns a success or duplicate message to the browser. | P0 |
| IN-3 | **Job-board import:** daily fetch from public feeds for companies in `config.yaml` (Greenhouse, Lever and Ashby job boards), plus RemoteOK, Himalayas (a short list of title searches), We Work Remotely RSS, Remotive and Jobicy (see `docs/job-boards.md` for the board review and each board's terms). Any other board with an RSS or Atom feed can be added in `config.yaml` under `extra_feeds` without code changes (Job Source "Other"). Boards without a feed are not scraped; their jobs come in through the paste-a-link form. Pre-filters before anything reaches HubSpot: title match (target, adjacent, and an `explore_titles` list for trying new directions, imported last and labelled on the deal), recent (≤ 14 days), and a location pre-filter that skips roles clearly limited to countries Peace can't work from. Scheduled runs are off until the `ENABLE_SCHEDULED_IMPORT` repository variable is `true`. | P0 |
| IN-4 | **Duplicate removal** on the normalised `job_url` (LinkedIn posts use the canonical `feed/update/urn:li:...` URL, so every link style for the same post matches). Cross-source duplicates (same company and title within 14 days) are skipped with a logged reason rather than created and archived, which saves records. | P0 |
| IN-5 | **Company upsert:** find or create the company by domain or name and link it to the deal. | P0 |
| IN-6 | **Poster contact (LinkedIn captures and pasted links):** create or link a contact with `pipeline_role = Poster`, using the profile link from the URL (IN-1c), plus any name, title or company the AI finds in the post text. If the same person posts again, the existing contact is reused (matched on profile link). | P0 |
| IN-7 | **LinkedIn job alerts:** Apps Script reads the Gmail label `job-alerts`, pulls out job links and posts them to the Worker. | P1 |
| IN-8 | **Daily cap:** at most 100 new deals imported from job boards per day (set for 15 applications a day; see the §3 decision), to keep review manageable (configurable). | P0 |

### 10.2 Qualify

| ID | Requirement | Priority |
|---|---|---|
| QU-1 | Process deals in `New`. Pull out job details into strict JSON (see §11.2). | P0 |
| QU-2 | **Hard filters:** archive if `remote_scope` is Not remote or Country-restricted to a country Peace can't work from, or if the title clearly doesn't match. Record the reason. | P0 |
| QU-3 | **Fit score (0–100)** using the rubric in §11.3. Store the score and reasons. | P0 |
| QU-4 | Score ≥ `fit_threshold` (default 70) → `Qualified`. Otherwise → `Archived`. | P0 |
| QU-5 | If the job text is too short or missing (for example a LinkedIn post with no description), try to fetch the apply URL's page text. If it's still missing, flag `pipeline_error` and leave it for manual review. | P1 |

### 10.3 Research (no email finding in v1)

| ID | Requirement | Priority |
|---|---|---|
| RE-1 | Fetch the company homepage or about page (public, respecting robots.txt) and produce a 3–5 bullet **company brief**: what they sell, to whom, stage or size if stated, and an angle for the cover letter. | P0 |
| RE-2 | Suggest 2–3 likely hiring-manager titles (for example Head of Growth, RevOps Lead, VP Marketing) for Peace to look up by hand. | P0 |
| RE-3 | Move to `Researched`. | P0 |

### 10.4 Draft

| ID | Requirement | Priority |
|---|---|---|
| DR-1 | Process `Researched` deals, highest fit score first, up to `daily_draft_cap` (20, set for 15 applications a day; see the §3 decision). | P0 |
| DR-2 | **Tailored CV:** the AI selects and rewords content **only from the master CV**, following the ATS rules in §12. It returns structured JSON, and the code renders the .docx from the template. | P0 |
| DR-3 | **Cover letter:** 200–300 words using the company brief and the job's top requirements, truthful, no clichés. Rendered as .docx. | P0 |
| DR-4 | **Connection note:** ≤ 300 characters, specific to the post or role. | P0 |
| DR-5 | **Follow-up message:** ≤ 120 words, usable as a LinkedIn message or an email. | P0 |
| DR-6 | **Keyword coverage:** pull out the job's key requirements, check which appear truthfully in the CV, store the coverage % and the missing keywords. Missing keywords must **not** be added if Peace lacks them. | P0 |
| DR-7 | **Truth check:** a second AI pass compares the tailored CV with the master CV and flags any claim that isn't supported. If anything is flagged, it's noted in `pipeline_error` for review. | P0 |
| DR-8 | Upload both files to HubSpot Files (private), store the links on the deal, and add a note summarising the drafts. | P0 |
| DR-9 | Move to `Ready for Review`. | P0 |
| DR-10 | File names: `Peace-George-CV-{Company}.docx`, `Peace-George-Cover-Letter-{Company}.docx`. | P0 |

### 10.5 Review and approval (human, in HubSpot)

| ID | Requirement | Priority |
|---|---|---|
| RV-1 | A board view filtered to `Ready for Review`, sorted by fit score. | P0 |
| RV-2 | Peace edits files and messages as needed, then moves the deal to `Approved` or `Archived`. | P0 |
| RV-3 | Peace applies, connects and messages by hand, then moves the deal to `Applied` and sets `applied_date`. | P0 |

### 10.6 Digest and nudges

| ID | Requirement | Priority |
|---|---|---|
| DG-1 | **Daily digest at 07:30 Lagos:** counts per stage, a list of `Ready for Review` deals (title, company, score, link), and any errors. | P0 |
| DG-2 | **Follow-up nudge:** deals in `Applied` for 5 or more days with no update get a HubSpot task and a mention in the digest. | P1 |
| DG-3 | **Weekly summary (Monday):** the funnel numbers in §3. | P1 |

### 10.7 Operations

| ID | Requirement | Priority |
|---|---|---|
| OP-1 | **Dry-run mode:** runs the full pipeline on sample jobs without writing to HubSpot or calling paid APIs. | P0 |
| OP-2 | Structured logs for each run (counts, timings, errors) in the GitHub Actions output. | P0 |
| OP-3 | A failed run emails Peace (GitHub Actions failure notification, plus a digest error section). | P0 |
| OP-4 | All modules are safe to re-run, so re-running never creates duplicates or re-drafts finished deals. | P0 |
| OP-5 | Every scheduled job can also be triggered by hand from the GitHub Actions page. | P0 |

---

## 11. AI specification

### 11.1 Provider
- A provider layer (`llm.py`) supports **Gemini** and **Claude**, chosen in `config.yaml`.
- **Decision (Phase 1):** use the **free Gemini tier** for development and production, because there's no budget yet. Upgrading to a paid tier (Gemini or Claude) is planned for Phase 2 (see §3 scale-up criteria). Switching is a config change.
- **Accepted risk:** Google's terms for the free tier say that prompts and responses may be used to improve Google's products and may be read by human reviewers, and they ask users not to submit personal information. Peace accepts this for her own CV content during Phase 1.
- **Data minimisation, so as little personal data as possible reaches the free tier:**
  - Peace's contact line (email, LinkedIn URL) is **never** sent to the AI. The code inserts it into the template.
  - Third-party contact data (poster names, profile links, any email addresses or phone numbers) is never sent to the AI. Before any job text is sent, the code **redacts emails, phone numbers and profile URLs**.
  - Poster details come from the URL (IN-1c), not from the AI.
  - Each prompt contains only the master CV sections it needs (for example, scoring sends a skills and tools summary, not the full CV).
- **Free-tier rate limits:** limits aren't guaranteed and can change. The code retries with backoff on rate-limit errors, spreads work across scheduled runs, and leaves anything unfinished for the next run instead of failing.

### 11.2 Extraction output (schema)
```json
{
  "job_title": "string",
  "company_name": "string",
  "company_domain": "string|null",
  "apply_url": "string|null",
  "remote_scope": "Worldwide|Region|Country-restricted|Unclear|Not remote",
  "eligible_regions": "string|null",
  "seniority": "Entry|Mid|Senior|Lead|Unclear",
  "salary_text": "string|null",
  "required_skills": ["string"],
  "tools_mentioned": ["string"],
  "poster_name": "string|null",
  "poster_profile_url": "string|null",
  "key_requirements": ["string"]
}
```
Outputs are checked against the schema. If the output is invalid, retry once, then flag `pipeline_error`.

### 11.3 Fit-score rubric (configurable weights)

| Factor | Points |
|---|---|
| Remote worldwide | 30 |
| Remote within a region Peace is eligible for | 20 |
| Remote scope unclear | 10 |
| Title matches a target role (GTM Engineer, Growth Engineer, Marketing Engineer, Marketing Automation, Growth or Revenue Operations, and AI operations and automation roles such as AI Operations, AI Automation, AI Implementation, AI Solutions; full list in `config.yaml`) | 25 |
| Adjacent title (Growth Marketing, Marketing Ops, GTM Strategist, Founder's Associate, Chief of Staff; full list in `config.yaml`) | 15 |
| Tools and skills overlap with the master CV | up to 20 |
| Seniority Entry or Mid (Senior allowed if requirements match) | 15 |
| Salary listed | 10 |

Hard filters (§10.2) are applied before scoring.

### 11.4 Prompts (stored in `/prompts`, version-controlled)
`extract.md`, `score.md`, `company_brief.md`, `tailor_cv.md`, `cover_letter.md`, `messages.md`, `truth_check.md`

**Rules shared by every drafting prompt:**
- Use only facts from the master CV.
- Mirror the job description's exact keyword phrasing where it's true.
- Spell out acronyms once, for example "Go-to-Market (GTM)".
- No clichés ("I am writing to express my interest…").
- Plain, confident, specific language.

### 11.5 Cost control
Drafting is capped each day, short models handle extraction and scoring, and the stronger model is used only for drafting.

---

## 12. CV generation specification

- **Template:** built by `scripts/build_templates.py` into `templates/`, rendered by `src/render_docx.py`. One column, plain-text safe, with section headings in capitals (`PROFESSIONAL SUMMARY`, `CORE SKILLS`, `TOOLS & TECHNOLOGIES`, `PROFESSIONAL EXPERIENCE`, `PROJECTS`, `EDUCATION`, `CERTIFICATIONS`, `LANGUAGES`).
- **No** tables, columns, text boxes, images, icons, or headers and footers.
- Bullets are plain hyphens. Dates use the format `Mon YYYY - Mon YYYY`.
- Contact line: `Remote | <email> | <LinkedIn URL>`. Location is shown as `Remote` with no country. **Decision (17 Nov 2026):** the no-country rule applies to the contact line only. Employer and education entries keep their locations as written in the master CV. The real values come from the `MASTER_CV` secret and are inserted by code, never by the AI. Portfolio link added later.
- **Two pages maximum.** Roles in reverse date order. Relevant roles get 3–5 bullets, others 1–2.
- **Optional roles** (tagged `OPTIONAL` in the master CV) appear **only** when the job specifically values agency, brand or content experience. Default: hidden.
- The AI controls bullet selection and wording. The code controls structure and order.
- Output: .docx (P0), PDF (P2).

### Master CV storage
- The master CV (YAML or Markdown) is stored as a **GitHub Secret** (`MASTER_CV`) and never committed.
- Each bullet is tagged by theme (for example `[GTM][OUTBOUND]`). Tools carry honest proficiency levels.

---

## 13. Non-functional requirements

| Area | Requirement |
|---|---|
| Reliability | A failure on one deal doesn't stop the run. Errors are recorded on the deal |
| Repeatability | Re-runs are safe (OP-4) |
| Performance | A full scheduled run finishes in under 15 minutes |
| Security | Secrets live only in GitHub and Cloudflare. The Worker requires a shared secret. HubSpot token permissions are kept to the minimum needed |
| Privacy | No personal data in the repo or logs. Data sent to the AI is minimised and redacted (§11.1). Contact data stays in HubSpot |
| Cost | $0 in Phase 1 (all free tiers, including free Gemini). Paid AI in Phase 2 (about $25 a month) |
| Maintainability | Modular code, typed config, version-controlled prompts, README for each module |
| Testability | Unit tests for parsers and scoring. Sample-data tests for the pipeline. Dry-run mode |

---

## 14. Scheduling (GitHub Actions, times in UTC; Lagos = UTC+1)

| Job | Schedule | Runs |
|---|---|---|
| `pipeline` | 05:00 and 13:00 UTC daily | intake (job boards) → qualify → research → draft |
| `process-captures` | Every 2 hours, 06:00–20:00 UTC | qualify → research → draft for new captures |
| `digest` | 06:30 UTC daily (07:30 Lagos) | Daily digest |
| `weekly` | Monday 07:00 UTC | Weekly summary (P1) |

**Notes:**
- Scheduled runs can start a few minutes late.
- On public repos, schedules pause after 60 days without repo activity.
- Every job can also be run by hand.

---

## 15. Repository structure

```
gtm-job-engine/
├── README.md                 # case study + setup guide
├── docs/
│   ├── PRD.md                # this document
│   ├── architecture.png
│   └── runbook.md            # how to operate & troubleshoot
├── config.yaml               # keywords, companies, rubric, caps, model choice
├── prompts/                  # versioned prompt files
├── src/
│   ├── hubspot_client.py
│   ├── llm.py
│   ├── sources/              # greenhouse.py, lever.py, ashby.py, remoteok.py, himalayas.py, wwr.py
│   ├── intake.py
│   ├── qualify.py
│   ├── research.py
│   ├── draft.py
│   ├── render_docx.py
│   └── digest.py
├── templates/                # cv_template.docx, cover_letter_template.docx
├── scripts/
│   └── setup_hubspot.py      # creates pipeline stages & properties
├── worker/                   # Cloudflare Worker + bookmarklet
├── apps_script/              # Gmail job-alert reader (P1)
├── tests/
│   └── fixtures/             # made-up sample jobs only
└── .github/workflows/        # pipeline.yml, digest.yml, weekly.yml, tests.yml
```

---

## 16. Configuration and secrets

### `config.yaml` (committed, no personal data)
```yaml
target_titles: ["GTM Engineer", "Growth Engineer", "Marketing Engineer",
                "Marketing Automation", "Growth Operations", "Revenue Operations"]
adjacent_titles: ["Growth Marketing", "Marketing Operations", "Founder's Associate"]
fit_threshold: 70
daily_import_cap: 100     # set for 15 a day (§3 decision)
daily_draft_cap: 20       # set for 15 a day (§3 decision)
followup_after_days: 5
llm:
  provider: gemini        # or claude
  fast_model: "<set at build time>"
  draft_model: "<set at build time>"
companies:
  greenhouse: []          # board tokens
  lever: []
  ashby: []
timezone: "Africa/Lagos"
```

### Secrets (never committed)

| Name | Where | Purpose |
|---|---|---|
| `HUBSPOT_TOKEN` | GitHub (copied into the Worker at deploy time) | HubSpot Service Key (§9.5) |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | GitHub | Lets the Deploy Worker workflow publish the Worker |
| `LLM_API_KEY` | GitHub | Gemini or Claude key |
| `MASTER_CV` | GitHub | Master CV content |
| `CAPTURE_SECRET` | GitHub (copied into the Worker at deploy time), typed once into the form on each device | Protects the capture endpoint |
| `DIGEST_TO_EMAIL` | GitHub | Digest recipient |
| Mail-sending credential | GitHub | For the digest email (method decided at build time) |

---

## 17. Milestones and acceptance criteria

| # | Milestone | Done when |
|---|---|---|
| M0 | **Foundations:** master CV, ATS template, rubric, target company list | Master CV approved by Peace. Template passes the plain-text paste test |
| M1 | **HubSpot setup:** Service Key, `setup_hubspot.py` | Pipeline, stages and properties exist. Board view saved |
| M2 | **Manual baseline:** 5 applications done fully by hand and timed, per pipeline step (sheet kept private; `scripts/baseline_summary.py` publishes aggregates to `docs/baseline.md`) | Baseline minutes recorded |
| M3 | **Intake:** job boards, capture bookmarklet, paste-a-link form and Worker | Capturing or pasting a post creates exactly one deal and a linked poster contact with the correct profile link. A repeat is flagged as a duplicate. A URL-only submission is flagged "Needs post text" |
| M4 | **Qualify and research** | Sample jobs score as expected. Hard filters archive restricted roles |
| M5 | **Draft** | A tailored CV passes the truth check, opens in Notepad cleanly after copy-paste, and is no more than 2 pages |
| M6 | **Operations:** schedules, digest, alerts, dry-run | 3 consecutive scheduled runs with no unhandled errors. Digest received |
| M7 | **Go live:** free Gemini key, real jobs | 5 applications a day for 5 days running |
| M8 | **Portfolio:** README case study, diagram, Loom, LinkedIn posts | Published and linked in LinkedIn Featured |
| M9 | **Hold 15 a day** | Caps are already set for 15 a day (§3 decision). Done when 15 applications a day run for 5 working days with quality holding steady (truth-check pass rate ≥ 90%, stable edit time) |

**Decision (14 Nov 2026): M2 runs in parallel with M3 and does not block the build.** Peace completes the 5 timed manual applications while intake is being built. To keep the baseline honest, the timed applications are done before she starts using the capture button or paste form. If that becomes impractical, the PRD will record that the baseline is partial or estimated.

**Decision (16 Nov 2026): the baseline uses 1 timed manual application instead of 5,** so the build is not held up. `docs/baseline.md` labels it as a small sample, and portfolio claims about time saved will say it is based on one application.

---

## 18. Risks and mitigations

| Risk | Mitigation |
|---|---|
| LinkedIn account restriction | No automation on LinkedIn. Capture is a human click or paste. Poster details come from the URL itself, and LinkedIn pages are never fetched by the system |
| Pasted link has no text, so requirements are unknown | "Needs post text" flag, listed in the digest. The system also follows any external job link in the text |
| AI invents experience | Master-CV-only prompts, a truth-check pass, human review |
| Job board feeds change or break | One module per source, error alerts, failures isolated |
| "Remote" roles that are actually location-restricted | Hard filter plus an "Unclear" flag for manual check |
| Personal data leaks | Secrets, a clean public repo, no contact data in prompts, redaction of emails, phones and profile URLs before AI calls |
| Free Gemini tier: data may be used for training or seen by human reviewers | Accepted risk for Phase 1 (Peace's own CV content only). Data minimisation in §11.1. Move to a paid tier in Phase 2 |
| Free Gemini tier rate limits hit or reduced | Retries with backoff, work spread over runs, daily caps. Switch model or provider in config |
| HubSpot free-plan limits (one pipeline, property caps, no multi-step workflows) | Automation lives in code. Properties kept lean |
| Too many drafts to review | Daily import and draft caps, sorted by fit score |
| Scheduled runs pause or start late | Manual trigger available. Repo stays active |

---

## 19. Future enhancements
- Email finding (Hunter or Apollo) once a work-domain email exists.
- Creating Gmail drafts for approved follow-ups.
- PDF export.
- A results dashboard (funnel by source and score band).
- Reusing modules for Workflow 2 (salon booking-site client acquisition).
- Learning loop: compare fit scores with actual replies to tune the rubric.

---

## 20. Portfolio deliverables
1. README case study: problem, design decisions (human-in-the-loop, no LinkedIn automation, truth check), architecture, stack, results.
2. Architecture diagram.
3. A 2–3 minute Loom of one job going from capture to drafts to approval, with contact data blurred.
4. Screenshots: HubSpot board, a tailored CV next to its job description, the digest.
5. A LinkedIn build-in-public series (3–4 posts), and a Featured and Projects entry.

---

## 21. Open questions
1. ~~Production AI provider~~ **Decided:** free Gemini tier in Phase 1. Paid Gemini or Claude to be chosen at Phase 2.
2. Digest email sending method (Gmail app password vs HubSpot vs another provider).
3. ~~HubSpot free-plan custom property limits~~ **Decided:** 10 in total. See §9.2.
4. The list of target companies' job boards (started in M0, finalised and verified in M3 when the source modules are built).

---

## 22. Glossary (plain English)

| Term | Meaning |
|---|---|
| **ATS** | Applicant Tracking System, the software companies use to store and screen CVs |
| **Pipeline / stage** | The columns a job moves through in HubSpot, like a to-do board |
| **Deal** | HubSpot's word for one opportunity. Here, one job application |
| **Service Key** | A secret key that lets our code read and write to your HubSpot (replaced "private app tokens" in 2026) |
| **GitHub Actions** | GitHub's alarm clock that runs our code on a schedule |
| **Cloudflare Worker** | A tiny always-awake program that catches your capture clicks |
| **Bookmarklet** | A browser bookmark that runs a small action when clicked |
| **Webhook / endpoint** | An internet address that receives data |
| **LLM** | The AI model (Gemini or Claude) that reads and writes |
| **Dry run** | A practice run with pretend data that changes nothing real |
| **Re-run safe** | Running it twice doesn't create duplicates |
| **Secret** | A password or key stored in a locked vault, never in the code |
