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

## Qualifying jobs (Milestone 4)
- **GitHub:** Actions > **Qualify jobs** > Run workflow. `preview` shows scores and reasons without changing HubSpot; `live` renames deals, fills in Fit Score, Remote Scope and Job Analysis, links the company, and moves each deal to **Qualified** (score >= `fit_threshold`) or **Archived**.
- **Locally:** `python scripts/qualify_jobs.py --offline` (made-up demo), `--preview`, or live.
- **Your own captures** (paste form, capture button) are never archived for a low score, only by the hard filters. Their Job Analysis says "Hand-picked by you" when they're below the threshold.
- **Retries:** the summary shows `AI answers retried for format` with a short reason, and the `AI format mode`. Frequent retries double free-tier usage, so report them.
- **Skipped deals:** a deal with anything in **Pipeline Error** is skipped (NEEDS POST TEXT, JOB TEXT TOO SHORT, AI ERROR). Fix the cause (for example, paste the job text into Deal description), clear the Pipeline Error field, and the next run picks it up.
- **Archived by mistake?** Read the reason at the top of **Job Analysis**, then drag the deal back to **New** (and fix the job text if needed) to re-score it, or straight to **Qualified**.
- **Tuning:** `fit_threshold` and `rubric` points in `config.yaml`; the prompt in `prompts/qualify.md`.
- **Free-tier quota:** at most `max_ai_calls_per_run` jobs per run, one request each. If the AI is busy, the run stops cleanly and the rest wait for the next run.

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
_Filled in at M6._
