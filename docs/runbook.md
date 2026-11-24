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

## Job-board import (Milestone 3)
- GitHub: **Actions > Import jobs > Run workflow**. "Dry run" is ticked by default: it reads the boards but writes nothing.
- Scheduled runs (06:17 and 14:17 Lagos) only happen when the repository variable `ENABLE_SCHEDULED_IMPORT` = `true` (**Settings > Secrets and variables > Actions > Variables**). Delete it or set it to `false` to pause.
- Locally: `python scripts/import_jobs.py --dry-run --offline` (sample data), `--dry-run` (real boards, fake HubSpot).
- **Checking the schedule:** Actions > **Import jobs**. Scheduled runs show the event **schedule**, your own runs show **workflow_dispatch**. GitHub's scheduler is best effort, so runs can start late (sometimes 30+ minutes) or occasionally be skipped; you can always run it by hand.
- The run summary lists what was fetched, filtered, created and skipped. A red run means a board or HubSpot call failed; the summary names it.
- Tuning: titles in `config.yaml` (`target_titles`, `adjacent_titles`, `excluded_title_words`), locations in `eligible_regions`, volume in `daily_import_cap`.

## Capturing jobs (paste form and capture button)
- **Phone:** open `https://gtm-job-engine-capture.<your-subdomain>.workers.dev/add`, paste the post link (LinkedIn app: **…** > **Copy link to post**), paste the post text, then tap **Save to HubSpot**. Add it to your home screen for one-tap access.
- **Laptop:** install the **+ Capture job** button from `/bookmarklet`. On a post, highlight the text, click the button, then **Save to HubSpot**.
- Replies: **Saved** (new deal), **Already captured** (duplicate), **Added the post text** (fills in an earlier link-only capture), or an error explaining what to do.
- The access key is asked for once per browser. "Use a different access key" clears it.
- **Same post, different link:** LinkedIn gives one post two IDs (address bar vs "Copy link to post"). A second capture of the same poster's post within 14 days is recognised and says "Looks like the same post…". If it really is a different post, paste its text and save again.
- **Poster details come from the link.** Links from "Copy link to post" (`linkedin.com/posts/<name>_...`) include the poster; address-bar links like `linkedin.com/feed/update/...` don't, so those deals have no poster contact.
- **Redeploying:** Actions > **Deploy Worker** > Run workflow. Do this after changing the Worker code or the `CAPTURE_SECRET` / `HUBSPOT_TOKEN` secrets.
- **Errors:** Cloudflare dashboard > Workers & Pages > `gtm-job-engine-capture` > **Logs**.
- **Poster details on the laptop:** open the post via **...** > **Copy link to post**, paste that link into the address bar, then use the button. Feed and search addresses (`feed/update/...`) don't include the poster.
- **Cloudflare API token:** if it was created with an expiry, renew it before then (Cloudflare > My Profile > API Tokens > Roll) and update the `CLOUDFLARE_API_TOKEN` GitHub Secret. The live Worker keeps running either way; only redeploys need the token.

## AI connection (Milestone 4)
- **Check it:** Actions > **Check AI connection** > Run workflow. It sends one made-up request and checks the master CV secret. The log shows only section names and sizes, never CV content.
- **Secrets:** `LLM_API_KEY` (Gemini key from aistudio.google.com/apikey) and `MASTER_CV` (the full master CV text).
- **Updating the master CV:** edit your local file, then in GitHub go to Settings > Secrets and variables > Actions, click the pencil on `MASTER_CV`, paste the whole new text and click **Update secret**.
- **Switching provider or model:** `config.yaml` > `llm` (`provider`, `fast_model`, `draft_model`), then update `LLM_API_KEY` if the provider changes.
- **Free-tier limits:** see your current limits at aistudio.google.com (signed in). If runs hit limits, lower `max_ai_calls_per_run` or raise `min_seconds_between_calls`.

## Qualifying and researching jobs (Milestone 4)
- **GitHub:** Actions > **Qualify, research and draft jobs** > Run workflow (qualify, then research, then draft, same mode). `preview` shows scores and reasons without changing HubSpot; `live` renames deals, fills in Fit Score, Remote Scope and Job Analysis, links the company, and moves each deal to **Qualified** (score >= `fit_threshold`) or **Archived**.
- **Locally:** `python scripts/qualify_jobs.py --offline` (made-up demo), `--preview`, or live.
- **Research:** each Qualified deal (highest Fit Score first) gets a company brief, a cover-letter angle and 2-3 hiring-manager titles to look up by hand, added to **Job Analysis**, and moves to **Researched**. If the company website gave little, the brief says it's based on the job posting only.
- **Missing websites:** research tries to find the company's site (job text clues, apply link, an AI suggestion, then name guesses), checks it loads and names the company, and only saves it if the AI confirms it's the same company. The summary shows `website found via ...` or `rejected <domain> (a different company)`. If it can't find or confirm one, add the domain to the company in HubSpot and move the deal back to **Qualified** to re-research.
- **Automatic runs:** after each scheduled import, and every 2 hours (07:47-21:47 Lagos, **Process captures** workflow), once the repository variable `ENABLE_SCHEDULED_AI` = `true`. Delete the variable to pause the AI steps; imports keep running.
- **Your own captures** (paste form, capture button) are never archived for a low score, only by the hard filters. Their Job Analysis says "Hand-picked by you" when they're below the threshold.
- **Retries:** the summary shows `AI answers retried for format` with a short reason, and the `AI format mode`. Frequent retries double free-tier usage, so report them.
- **Skipped deals:** a deal with anything in **Pipeline Error** is skipped (NEEDS POST TEXT, JOB TEXT TOO SHORT, AI ERROR). Fix the cause (for example, paste the job text into Deal description), clear the Pipeline Error field, and the next run picks it up.
- **Archived by mistake?** Read the reason at the top of **Job Analysis**, then drag the deal back to **New** (and fix the job text if needed) to re-score it, or straight to **Qualified**.
- **Tuning:** `fit_threshold` and `rubric` points in `config.yaml`; the prompt in `prompts/qualify.md`.
- **Free-tier quota:** at most `max_ai_calls_per_run` jobs per run, one request each. If the AI is busy, the run stops cleanly and the rest wait for the next run.

## Drafting applications (Milestone 5)
- **What it makes** for each **Researched** deal (highest Fit Score first, up to `daily_draft_cap` a day): a tailored CV and a cover letter (Word files), a LinkedIn connection note (300 characters max), a follow-up message (120 words max) and a keyword coverage check.
- **Where it goes (live):** both files are uploaded to HubSpot's file manager as **private** files (folder `gtm-job-engine/drafts`) and attached to a note on the deal. The deal's **Job Analysis** gets a `Drafts (date)` section with the truth-check result, coverage, missing keywords and both messages; **Keyword Coverage** is filled in; the deal moves to **Ready for Review**. Re-drafting replaces the old `Drafts` section.
- **Truth check:** a second AI pass compares every reworded claim with your master CV. If it finds problems (or couldn't run), **Pipeline Error** says `TRUTH CHECK: ...` and the issues are listed in Job Analysis. Fix the Word files, then clear Pipeline Error. Skills, tools, employers, titles and dates that aren't in the master CV are dropped by code before the AI ever sees the result.
- **Backup AI model:** if the draft model stays busy (Gemini 503/429) after its retries, the draft is written by `draft_backup_model` (config.yaml) instead, and the rest of that run uses the backup. The summary says `Backup AI model used for n answer(s)` and the deal's Drafts notes say to check the wording. Remove the line from config.yaml to turn this off.
- **If saving fails** (for example a missing key permission), the deal stays in **Researched** with `DRAFT ERROR: ...` in Pipeline Error. Fix the cause, clear the field, and the next run retries.
- **GitHub:** Actions > **Qualify, research and draft jobs** > Run workflow. `preview` drafts and checks but writes nothing to HubSpot (the files stay on GitHub's temporary machine and are deleted; the log shows counts only).
- **Locally:** `python scripts/draft_jobs.py --offline` (made-up demo), `--preview` (real deals, files saved in `output/drafts`, git-ignored), or live.
- **Automatic drafting:** after scheduled imports and in **Process captures**, only when the repository variable `ENABLE_SCHEDULED_DRAFTS` = `true` (and `ENABLE_SCHEDULED_AI` = `true` for the import workflow). Delete it to pause drafting only.
- **HubSpot key permission:** the Service Key needs the `files` scope to upload. If a run says `required scopes`, add the scope it names (Development > Keys > Service keys > your key > Edit scopes) and run again.
- **Before applying:** open the CV, copy all, paste into Notepad: it should read cleanly, top to bottom. Check it's no more than 2 pages in Word. You send everything yourself; nothing is applied or sent automatically.

## Email: daily digest and alerts (Milestone 6)
- **Daily digest** (about 07:27 Lagos, workflow **Daily digest**): deals Ready for Review (fit score, coverage, link), follow-ups due (Applied with no update for `digest.follow_up_days`, default 5), deals that need you (anything in Pipeline Error, except Archived and Rejected), scheduled runs that failed in the last 24 hours, and counts per stage. It only reads HubSpot.
- **Alerts:** if a scheduled Import jobs, Process captures or Daily digest run fails, you get an email with a link to the run. GitHub also emails failed scheduled runs to you by default.
- **Sending:** through Gmail with an app password (the system only sends mail; it never reads your inbox). Secrets: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, and optionally `DIGEST_TO_EMAIL` (defaults to the Gmail address).
- **Turning on the daily schedule:** repository variable `ENABLE_DIGEST` = `true`. Delete it to pause.
- **By hand:** Actions > **Daily digest** > Run workflow (`send` emails it now; `preview` shows counts only). Locally: `python scripts/send_digest.py --offline` (made-up deals), `--preview` (saves `output/digest-preview.html`), or no flag to send.
- **Follow-up tasks:** each digest run adds a HubSpot task (`Follow up: <deal>`, due today) to Applied deals with no update for 5 days. Find them under CRM > Tasks (they have no owner, so use the "All tasks" view). Send the follow-up, mark the task complete and move the deal to Followed Up. A deal never gets a second task while one is open.
- **Weekly summary** (Mondays about 08:07 Lagos, workflow **Weekly summary**, same `ENABLE_DIGEST` switch): new jobs, qualified rate, applied this week, keyword coverage, truth-check pass rate, interview rate and failed runs. Numbers only. **Set Applied Date on a deal when you apply**, or the applied count stays at 0. By hand: Actions > Weekly summary > Run workflow; locally `python scripts/send_weekly.py --offline` or `--preview`.
- **Changing the app password:** create a new one in your Google Account (Security > App passwords), update `GMAIL_APP_PASSWORD`, and delete the old one in Google.

## Adding job titles
All title lists are in `config.yaml`. Edit them on github.com: open the file, click the pencil icon, change it, then **Commit changes**.

| List | Use it for | Priority under the daily cap |
|---|---|---|
| `target_titles` | Your core roles | First |
| `adjacent_titles` | Close fits you always want | Second |
| `explore_titles` | New directions you're trying out | Last |
| `excluded_title_words` | Words that rule a job out, even if a list matches | Always wins |

**To try a new direction**, add it under `explore_titles`, one per line, with two spaces, a hyphen and a space in front:
```yaml
explore_titles:
  - Lifecycle Marketing
  - CRM Manager
```
- Matching is by phrase, ignoring capitals and punctuation: "CRM Manager" also matches "Senior CRM Manager (Remote)".
- Each explore deal's description says `Matched title list: explore`, and the import summary shows `Matches by title list` so you can see what each list brings in.
- After a week or two, move titles that bring good roles up to `adjacent_titles` and delete ones that don't.
- Each explore title is also searched on Himalayas, so keep the list to about 5.

## Adding a new job board
The boards already reviewed, with their verdicts, are in [job-boards.md](job-boards.md).

**1. Find the board's feed.** Look for an RSS icon, or a "Subscribe" or "RSS" link, often in the page footer. You can also try adding `/rss`, `/feed` or `.rss` to the board's jobs page address. A feed link opens as a page of code-like text (XML).

**2. Add it on github.com (no coding needed).**
1. Open the repo, click `config.yaml`, then click the pencil icon (Edit).
2. Find `extra_feeds: []` near the bottom and replace it with:
   ```yaml
   extra_feeds:
     - name: Board name
       url: https://the-feed-link
   ```
   To add more boards, repeat the two lines starting with `- name:`. Keep the spacing exactly the same.
3. Click **Commit changes**. The **Tests** workflow checks that the file is still valid.
4. Run **Actions > Import jobs** with **Dry run** ticked. The summary shows how many jobs the new board gave.

**Other cases:**
- **A company's own careers page on Greenhouse, Lever or Ashby:** add its board token under `companies:` instead. The token is the name in the link, e.g. `jobs.lever.co/<token>`.
- **A board with no feed:** it can't be imported automatically (we don't scrape web pages). Use the paste-a-link form for jobs you find there.
- **To pause a board:** add `enabled: false` under it.

## Secrets
Listed in [PRD §16](PRD.md#16-configuration-and-secrets). Stored only in GitHub Secrets and Cloudflare secrets. Never paste them into code, chat or issues.

## Troubleshooting
- **A failed-run email arrived:** open the link, click the red step and read its last lines. Busy AI (Gemini 503/429) needs nothing: the deals wait for the next run. A HubSpot `required scopes` message means the Service Key needs that scope added (Development > Keys > Service keys > GTM Job Engine > Edit).
- **Digest run is red with "Follow-up tasks failed":** the digest was still emailed. If the message mentions `required scopes`, add the scope names it lists to the Service Key (Development > Keys > Service keys > GTM Job Engine > Edit > Add new scope), then re-run Daily digest.
- **No digest arrived:** check the Daily digest run on GitHub. "Gmail refused the login" means the app password is wrong or was deleted: make a new one and update `GMAIL_APP_PASSWORD`. Also check your spam folder once and mark it Not spam.
- **A deal is stuck:** look at its Pipeline Error field, fix the cause, then clear the field. It's picked up on the next run.
- **Schedules stopped:** GitHub pauses schedules on public repos after 60 days with no commits. Any commit (even a docs edit) restarts them.
