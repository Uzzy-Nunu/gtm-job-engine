# Target companies

The engine reads these companies' own job boards every import run (twice a day).
They were chosen on 24 Nov 2026 for fit and hiring signal:

- **Fit (ICP):** remote-first or globally hiring companies in SaaS, AI, developer tools,
  GTM and marketing tooling, fintech and African tech, from startup to mid-size.
- **Hiring signal:** a live public board on Greenhouse, Lever or Ashby with open roles,
  checked with `scripts/check_company_boards.py` on the day they were added.
- **Readable:** only Greenhouse, Lever and Ashby boards have public APIs the engine
  can read. Companies on other systems are listed at the end for capturing by hand.

Each import keeps only roles that are remote, open to Peace's regions (worldwide,
EMEA, Africa, Nigeria, Europe time zones) and match a title list. Most of these
companies also post US-only or country-only roles, which the filters drop.

## First check (24 Nov 2026)

79 boards found and live. 39 had remote roles open to Peace's regions; 6 had roles
matching the title lists at the time (9 roles). Adding the boards and the new
explore titles raised a full import from 13 matching roles to the figures in
[the import summary](#how-to-re-check).

| ATS | Companies |
|---|---|
| Greenhouse (38) | Canonical, GitLab, Automattic, Wikimedia Foundation, Moniepoint, ALX Africa, Fingerprint, Netlify, Storyblok, Amplemarket, Remote, DoiT, Customer.io, SE Ranking, Mozilla, OKX, Bybit, Consensys, OpenZeppelin, Upsun, PlanetScale, Bitwarden, Invisible Technologies, Toloka, Udacity, HeyGen, Chainguard, Apollo.io, ZoomInfo, Pendo, Postscript, Fivetran, Luno, Jumia, Zipline, OfferZen, TransferGo, Thunes |
| Lever (9) | Contentsquare (Hotjar), Toptal, Metabase, Offchain Labs, Superside, MoonPay, 90 Seconds, Brevo, Outreach |
| Ashby (32) | Clay, lemlist, n8n, Zapier, PostHog, Supabase, Oyster, Circle, Kit, Chili Piper, ElevenLabs, Linear, RevenueCat, Andela, M-KOPA, LemFi, Help Scout, Buffer, Railway, Prefect, GitBook, Wistia, Percona, Restream, EverAI, Sardine, Deepgram, SearchApi, TestGorilla, Gorgias, Cohere, Kestra |

Board tokens, names and websites are in `config.yaml` under `companies:`.

## Worth watching by hand (no readable board)

These fit the profile but use another hiring system (Workable, BambooHR or their own
site). Check their careers pages occasionally and add good roles with the paste form.

| Company | Why |
|---|---|
| Deel | Global employer of record; hundreds of roles on its own site |
| Paystack | Nigerian fintech; own careers site |
| Flutterwave | Pan-African payments; BambooHR |
| Kuda | Nigerian neobank; Workable |
| Korapay | All-remote, hires almost anywhere; Workable |
| Yellow Card | Pan-African crypto; BambooHR |
| Chipper Cash | African payments; own careers page |
| RemotePass | Employer of record; has posted GTM Engineer roles |
| WorkMotion | Employer of record; has posted GTM Engineer roles (Clay, Make, HubSpot) |
| Toggl | Remote-first; its board link didn't respond to the API |
| Juicyway | Lagos fintech; posted a Growth and GTM Engineer role |
| Doist, Instantly, HeyReach | Remote GTM and productivity tooling |

Tokens that look right but belong to other companies were left out: `doit` (Ashby),
`sabi` (Ashby), `grey` (Greenhouse), `solutions` (Greenhouse).

## How to re-check

1. Put candidates in a text file, one per line: `Name | greenhouse | token`
   (use `any` instead of the ATS name to try all three).
2. Run `python scripts/check_company_boards.py candidates.txt`.
3. Add boards that are live, ideally with remote roles open to your regions, to
   `config.yaml` under `companies:`.

A board with no matching roles today can still be worth keeping: new roles are
picked up as soon as they're posted.
