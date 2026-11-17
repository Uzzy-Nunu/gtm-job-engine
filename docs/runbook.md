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
- Scheduled runs (06:00 and 14:00 Lagos) only happen when the repository variable `ENABLE_SCHEDULED_IMPORT` = `true` (**Settings > Secrets and variables > Actions > Variables**). Delete it or set it to `false` to pause.
- Locally: `python scripts/import_jobs.py --dry-run --offline` (sample data), `--dry-run` (real boards, fake HubSpot).
- The run summary lists what was fetched, filtered, created and skipped. A red run means a board or HubSpot call failed; the summary names it.
- Tuning: titles in `config.yaml` (`target_titles`, `adjacent_titles`, `excluded_title_words`), locations in `eligible_regions`, volume in `daily_import_cap`.

## Capturing jobs (paste form and capture button)
- **Phone:** open `https://gtm-job-engine-capture.<your-subdomain>.workers.dev/add`, paste the post link (LinkedIn app: **…** > **Copy link to post**), paste the post text, then tap **Save to HubSpot**. Add it to your home screen for one-tap access.
- **Laptop:** install the **+ Capture job** button from `/bookmarklet`. On a post, highlight the text, click the button, then **Save to HubSpot**.
- Replies: **Saved** (new deal), **Already captured** (duplicate), **Added the post text** (fills in an earlier link-only capture), or an error explaining what to do.
- The access key is asked for once per browser. "Use a different access key" clears it.
- **Redeploying:** Actions > **Deploy Worker** > Run workflow. Do this after changing the Worker code or the `CAPTURE_SECRET` / `HUBSPOT_TOKEN` secrets.
- **Errors:** Cloudflare dashboard > Workers & Pages > `gtm-job-engine-capture` > **Logs**.

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
