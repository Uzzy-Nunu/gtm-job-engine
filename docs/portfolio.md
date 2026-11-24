# Portfolio material (Milestone 8)

Ready-to-use material for presenting the GTM Job Engine: a demo video script and
LinkedIn post drafts. Every number here is measured (see the README's Results);
update them as live results come in. Never show real deal names, CV text or
contact details on screen: use the offline demos or blur HubSpot.

## Demo video script (Loom, about 4 minutes)

**Before recording:** open the README on GitHub, HubSpot (Review queue view, real
names blurred or a filtered view), the Actions tab, and a terminal with the offline
demos ready. Close email and chat apps.

| Time | Show | Say (in your own words) |
|---|---|---|
| 0:00-0:30 | README top and diagram | "Applying well is slow: my baseline was 120 minutes for one quality application. Applying badly at scale doesn't work. So I built a system that does the research and drafting, and keeps me in charge of every decision." |
| 0:30-1:15 | Diagram, then Actions tab (scheduled runs) | "Twice a day it reads 4,000+ postings from job boards, 79 company careers pages and my LinkedIn job-alert emails. It keeps only roles that are remote and open to someone in Nigeria, because most 'remote' GTM roles are US-only." |
| 1:15-2:00 | Qualify step log with score breakdowns | "The AI reads each job and judges the skills match; the scoring rules are plain code, so every score explains itself. When almost everything was being archived, I built a report to find out why, fixed the scoring, and re-scored the same jobs to check: 9 of 15 qualified, the weak fits stayed out." |
| 2:00-3:00 | HubSpot Review queue, one deal: Job Analysis, attached CV and cover letter | "For each qualified job it researches the company and drafts a tailored, two-page ATS CV, a cover letter and outreach messages. The AI can only pick facts from my master CV; code rebuilds the CV from the source, and a second AI pass checks every changed line." |
| 3:00-3:40 | Digest email (blurred), weekly summary lines | "Every morning I get a digest of what's ready, what needs follow-up and anything that broke. Mondays I get the funnel numbers and progress towards 15 applications a day." |
| 3:40-4:00 | README design decisions table | "Nothing is sent or submitted without me. No LinkedIn automation. No personal data in the public repo. Built with Python, HubSpot, Gemini, Cloudflare and GitHub Actions." |

## LinkedIn post drafts

Edit freely so they sound like you. Attach the diagram (screenshot of the README
diagram) or the demo video. Add the repo link in the first comment if you prefer.

### Post 1: the launch

> I spent the last two weeks building my own job-search engine, and today it's live.
>
> The problem: one quality application took me 120 minutes by hand. Research, fit, tailoring the CV so AI screening ranks it, a cover letter, outreach. And most "remote" GTM roles turn out to be US-only.
>
> What I built:
> - Reads 4,000+ postings a day from job boards, 79 company careers pages and my LinkedIn job alerts
> - Keeps only roles that are remote and open to me
> - Scores fit (AI reads the job, plain code does the scoring, so every score explains itself)
> - Researches the company and drafts a tailored ATS CV, cover letter and outreach messages
> - Truth-checks every line against my master CV
> - Puts it all in HubSpot for me to review. Nothing is sent without me.
>
> Stack: Python, HubSpot, Gemini, Cloudflare Workers, GitHub Actions.
>
> Next: 5 applications a day for a week, then 15. I'll share what the numbers say.
>
> Repo and write-up: [link]

### Post 2: the lesson (after a few days of use)

> My job engine was archiving 19 out of every 20 jobs. The fix wasn't more AI. It was a report.
>
> I built a read-only "archive report" that counted why each job was rejected. Two things stood out:
> 1. The AI was judging my skills from a list of tools, without seeing my experience. Skills match averaged 5.6 out of 20.
> 2. Senior roles scored zero for seniority unless I matched every requirement.
>
> So I gave the AI an experience overview (no employer names, no contact details), gave near-fit senior roles partial credit, and made the skills match worth more than "salary listed".
>
> Then I re-scored the same 15 jobs before going live: 9 qualified, including the roles I actually want. The weak fits stayed out.
>
> GTM lesson that applies to any funnel: before you tune the scoring, measure why things fall out.

### Post 3: results (after M7 / M9)

> Fill in from the weekly summary: applications sent, qualified rate, truth-check pass rate, interviews, and (if you track it) minutes per application against the 120-minute baseline. Real numbers only.

## Publishing checklist (M8 done when all are ticked)

- [ ] Record the demo video and add its link to the README (under "The approach")
- [ ] Publish post 1 with the diagram or video
- [ ] Add the repo (or the post) to LinkedIn Featured
- [ ] After a week of use, update the README Results and publish post 2
