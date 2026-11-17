# Job boards

Which boards the import reads, and why others are not read automatically. Reviewed 17 Nov 2026.

**Rules for automatic reading:** the board must offer a public feed (RSS/Atom) or API, list remote roles relevant to GTM, growth, marketing ops or RevOps, and allow automated reading in its terms. Web pages are never scraped, and LinkedIn is never contacted.

## Read automatically

| Board | How | Notes |
|---|---|---|
| RemoteOK | Public API | Credit RemoteOK and link back to the listing |
| Himalayas | Public search API, 12 searches per run | Rate-limited; searches are spaced out |
| We Work Remotely | RSS (3 categories) | |
| Remotive | Public API, 1 request per run | Terms: max about 4 requests a day, link back, name Remotive as the source, don't re-post jobs to other job sites. Jobs are delayed 24 hours |
| Jobicy | Public API, regions `anywhere` and `emea` | Terms allow internal applications; at most one pass per hour; credit Jobicy |
| Inclusively Remote | RSS (`/jobs/feed/`), via `extra_feeds` | Latest 10 jobs only, about 3 a week. Titles carry no company name, so deals start as "Title - company TBC" until Qualify fills it in. Uses the stable item ID as the job link. Terms don't restrict reading its public feed |
| Greenhouse, Lever, Ashby | Public job-board APIs | Per company, listed under `companies` in `config.yaml` |
| Any RSS/Atom board | `extra_feeds` in `config.yaml` | See the runbook: "Adding a new job board" |

## Reviewed, not read automatically

| Board | Verdict | Why |
|---|---|---|
| Remote Hunt | Already covered | Redirects to We Work Remotely |
| PowerToFly, RemoteHub, Dynamite Jobs, JustRemote, Flexa, Idealist | Use the paste-a-link form | No public job feed or API |
| The Muse | Use the paste-a-link form | Developer docs not accessible to confirm the API and its terms |
| Remote Woman, Remote Work Hub | Use the paste-a-link form | Their feeds carry blog posts, not jobs |
| RemoteJobr | Use the paste-a-link form | Requires login |
| Remoters | Use the paste-a-link form | Bot protection; no feed |
| Remote Jobs Club, Jobscribe, GoRemote, Jobs in Pods, RemoteBaba, Awesome Jobs | Not reachable when checked | Expired security certificate or the address didn't resolve. Worth re-checking later |
| WordPress Jobs, Laravel Jobs, Ruby Now, Jobmote | Not relevant | Developer-only boards (Jobmote now redirects to a developer site) |
| Virtual Assistant Jobs, OutsourcingJobs.ph, Outsourcing Insight, Outsourcely, CloudPeeps | Not relevant | Virtual-assistant, outsourcing or freelance marketplaces |
| Simply Communicate, TechJobs, Crossover | Not relevant | Internal comms (UK), non-remote tech, or a single company's own hiring |
