# Capture Worker

A Cloudflare Worker that turns a LinkedIn hiring post or job link into a HubSpot deal in seconds (PRD §10.1 IN-1, IN-1b, IN-1c, IN-2).

| Route | What it does |
|---|---|
| `GET /add` | Phone-friendly paste-a-link form |
| `GET /bookmarklet` | Install page for the **+ Capture job** browser button |
| `POST /capture` | JSON `{url, text?, notes?}` with header `X-Capture-Secret`; creates or updates the deal |
| `GET /health` | Returns `ok` |

## Design choices
- **No LinkedIn automation.** The Worker reads the post's ID and poster from the URL text only. Post text comes from Peace (pasted, or highlighted before clicking the bookmarklet).
- **The access key never sits in a link or the bookmarklet.** It's typed once into the form and kept in that browser. The bookmarklet only opens the form and fills it in through the URL `#fragment`, which browsers never send to a server.
- **Same rules as the Python intake.** `src/urls.js` and `src/intake.js` are twins of `src/urls.py` and `src/intake.py`. Both are tested against `tests/fixtures/linkedin_urls.json`.
- **Instant answers:** created, duplicate, updated (post text added later), or a clear error.
- **Hardened pages:** strict Content-Security-Policy with per-request nonces, no framing, no indexing, and a constant-time key check.

## Develop
```bash
cd worker
npm test            # Node 24+, no dependencies
```

## Deploy
GitHub: **Actions > Deploy Worker > Run workflow**. The workflow runs the tests, then publishes with Wrangler and copies `HUBSPOT_TOKEN` and `CAPTURE_SECRET` from GitHub Secrets into the Worker. It also needs the `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets.
