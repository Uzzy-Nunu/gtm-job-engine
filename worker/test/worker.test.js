// Worker tests: M3 acceptance criteria (PRD §17) through the real request
// handler, plus security checks. Fake HubSpot, made-up data only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { handle, sameSecret } from "../src/index.js";
import { similarText } from "../src/intake.js";
import { bookmarkletCode } from "../src/pages.js";
import { createFakeHubSpot } from "./fake-hubspot.js";

const SECRET = "test-secret-0123456789";
const ENV = { CAPTURE_SECRET: SECRET, HUBSPOT_TOKEN: "fake-token" };
const ORIGIN = "https://capture.example.workers.dev";
const POST = "https://www.linkedin.com/posts/jane-doe-123_hiring-gtm-activity-7390000000000000001-AbCd?utm_source=share";
const SAME_POST = "https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001/";
const TEXT = "We're hiring a GTM Engineer, remote worldwide. Python, Clay, HubSpot.";

// Cloudflare throws "Illegal invocation" when fetch() is called as a method
// of another object. This wrapper behaves the same way, so tests catch it.
function cloudflareStrict(fetchImpl) {
  return function strictFetch(url, init) {
    if (this !== undefined && this !== globalThis) {
      throw new TypeError("Illegal invocation: function called with incorrect `this` reference");
    }
    return fetchImpl(url, init);
  };
}

function setup() {
  const hs = createFakeHubSpot();
  const send = async (payload, { secret = SECRET, env = ENV } = {}) => {
    const req = new Request(`${ORIGIN}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Capture-Secret": secret },
      body: typeof payload === "string" ? payload : JSON.stringify(payload),
    });
    const resp = await handle(req, env, { fetchImpl: cloudflareStrict(hs.fetch), sleep: async () => {} });
    return { status: resp.status, body: await resp.json() };
  };
  return { hs, send };
}

// --- PRD M3 acceptance criteria ---------------------------------------

test("capture creates exactly one deal and a linked poster contact", async () => {
  const { hs, send } = setup();
  const r = await send({ url: POST, text: TEXT });
  assert.equal(r.status, 200);
  assert.equal(r.body.status, "created");
  assert.equal(hs.all("deals").length, 1);
  assert.equal(hs.all("contacts").length, 1);
  const deal = hs.all("deals")[0].properties;
  assert.equal(deal.job_url, "https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001");
  assert.equal(deal.job_source, "LinkedIn Post");
  assert.equal(hs.stageLabel(deal.dealstage), "New");
  assert.equal(deal.description, TEXT);
  const contact = hs.all("contacts")[0];
  assert.equal(contact.properties.hs_linkedin_url, "https://www.linkedin.com/in/jane-doe-123");
  assert.equal(contact.properties.lastname, "Doe (unconfirmed)");
  assert.deepEqual(hs.linked("deals", r.body.dealId, "contacts"), [contact.id]);
});

test("a repeat capture is flagged as a duplicate", async () => {
  const { hs, send } = setup();
  const first = await send({ url: POST, text: TEXT });
  const again = await send({ url: SAME_POST, text: TEXT });
  assert.equal(again.body.status, "duplicate");
  assert.equal(again.body.dealId, first.body.dealId);
  assert.equal(hs.all("deals").length, 1);
});

test("URL-only capture is flagged NEEDS POST TEXT, then filled in by a resubmit", async () => {
  const { hs, send } = setup();
  const r = await send({ url: POST });
  assert.ok(r.body.flags.includes("NEEDS POST TEXT"));
  assert.ok(hs.all("deals")[0].properties.pipeline_error.startsWith("NEEDS POST TEXT"));
  const later = await send({ url: POST, text: TEXT, notes: "from my phone" });
  assert.equal(later.body.status, "updated");
  const deal = hs.all("deals")[0].properties;
  assert.equal(deal.pipeline_error, "");
  assert.ok(deal.description.startsWith(TEXT));
  assert.ok(deal.description.includes("Notes from Peace ---\nfrom my phone"));
  assert.equal(hs.all("deals").length, 1);
});

// --- other intake rules -------------------------------------------------

test("external job link in the post becomes apply URL and company", async () => {
  const { hs, send } = setup();
  const r = await send({ url: POST, text: `${TEXT} Apply: https://careers.samplecorp.example/jobs/42?utm_source=li` });
  const deal = hs.all("deals")[0].properties;
  assert.equal(deal.apply_url, "https://careers.samplecorp.example/jobs/42");
  assert.deepEqual(hs.all("companies").map((c) => c.properties.domain), ["samplecorp.example"]);
  assert.equal(hs.linked("deals", r.body.dealId, "companies").length, 1);
});

test("same poster twice reuses the contact", async () => {
  const { hs, send } = setup();
  await send({ url: POST, text: TEXT });
  await send({ url: "https://www.linkedin.com/posts/jane-doe-123_revops-activity-7395555555555555555-Xx", text: "Another role." });
  assert.equal(hs.all("deals").length, 2);
  assert.equal(hs.all("contacts").length, 1);
});

test("a company job link works too", async () => {
  const { hs, send } = setup();
  const r = await send({ url: "https://boards.greenhouse.io/samplecorp/jobs/7?gh_src=x" });
  assert.equal(r.body.status, "created");
  const deal = hs.all("deals")[0].properties;
  assert.equal(deal.job_source, "Greenhouse");
  assert.equal(deal.job_url, "https://boards.greenhouse.io/samplecorp/jobs/7");
  assert.deepEqual(r.body.flags, []);
});

test("short lnkd.in links get a helpful error and create nothing", async () => {
  const { hs, send } = setup();
  const r = await send({ url: "https://lnkd.in/abc" });
  assert.equal(r.status, 422);
  assert.match(r.body.message, /Copy link to post/);
  assert.equal(hs.all("deals").length, 0);
});

test("missing pipeline is a loud error", async () => {
  const { hs, send } = setup();
  hs.state.pipeline.label = "Sales Pipeline";
  const r = await send({ url: POST, text: TEXT });
  assert.equal(r.body.status, "error");
  assert.match(r.body.message, /Run Setup HubSpot/);
});

// --- security -------------------------------------------------------------

test("wrong or missing access key is refused before touching HubSpot", async () => {
  const { hs, send } = setup();
  assert.equal((await send({ url: POST }, { secret: "wrong" })).status, 401);
  assert.equal((await send({ url: POST }, { secret: "" })).status, 401);
  assert.equal(hs.state.calls.length, 0);
});

test("Worker without a proper CAPTURE_SECRET refuses captures", async () => {
  const { send } = setup();
  const r = await send({ url: POST }, { env: { HUBSPOT_TOKEN: "x", CAPTURE_SECRET: "short" } });
  assert.equal(r.status, 500);
});

test("bad requests get clear errors", async () => {
  const { send } = setup();
  assert.equal((await send("not json")).status, 400);
  assert.equal((await send({ text: "no url" })).status, 400);
  assert.equal((await send({ url: POST, text: "x".repeat(100_001) })).status, 413);
});

test("sameSecret compares exactly", () => {
  assert.ok(sameSecret("abc", "abc"));
  assert.ok(!sameSecret("abc", "abd"));
  assert.ok(!sameSecret("abc", "abcd"));
  assert.ok(!sameSecret(undefined, "abc"));
});

test("form page is served with a matching CSP nonce and no secrets", async () => {
  const resp = await handle(new Request(`${ORIGIN}/add`), ENV);
  const body = await resp.text();
  const csp = resp.headers.get("Content-Security-Policy");
  const nonce = csp.match(/'nonce-([a-f0-9]+)'/)[1];
  assert.ok(body.includes(`<script nonce="${nonce}">`));
  assert.ok(!body.includes(SECRET) && !body.includes("fake-token"));
  assert.ok(!/ style="/.test(body), "inline style attributes would be blocked by the CSP");
  assert.equal(resp.headers.get("X-Frame-Options"), "DENY");
});

test("bookmarklet reads only the address and highlighted text, and holds no secret", async () => {
  const code = bookmarkletCode(ORIGIN);
  assert.ok(code.startsWith("javascript:"));
  assert.ok(code.includes(`${ORIGIN}/add#u=`));
  assert.ok(code.includes("getSelection()") && code.includes("location.href"));
  assert.ok(!/fetch|XMLHttpRequest|document\.(body|querySelector)/.test(code));
  const page = await (await handle(new Request(`${ORIGIN}/bookmarklet`), ENV)).text();
  assert.ok(page.includes(`${ORIGIN}/add#u=`) && !page.includes(SECRET));
});

test("root redirects to the form; unknown paths are 404", async () => {
  const root = await handle(new Request(`${ORIGIN}/`), ENV);
  assert.equal(root.status, 302);
  assert.equal(root.headers.get("Location"), `${ORIGIN}/add`);
  assert.equal((await handle(new Request(`${ORIGIN}/nope`), ENV)).status, 404);
  assert.equal(await (await handle(new Request(`${ORIGIN}/health`), ENV)).text(), "ok");
});

test("server errors say what went wrong (no secrets)", async () => {
  const req = new Request(`${ORIGIN}/capture`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Capture-Secret": SECRET },
    body: JSON.stringify({ url: POST, text: TEXT }),
  });
  const resp = await handle(req, { CAPTURE_SECRET: SECRET }, {});   // no HUBSPOT_TOKEN on the Worker
  const body = await resp.json();
  assert.equal(resp.status, 500);
  assert.match(body.message, /HUBSPOT_TOKEN is not set/);
  assert.ok(!body.message.includes(SECRET));
});

// --- one post, two LinkedIn IDs (activity vs ugcPost) ---------------------
const POST_ACTIVITY = "https://www.linkedin.com/posts/jane-doe-123_hiring-activity-7390000000000000001-AbCd";
const POST_UGC = "https://www.linkedin.com/posts/jane-doe-123_hiring-gtm-ugcPost-7391111111111111111-Zz9Y?utm_source=share";

test("same post captured with its other ID and no text is a duplicate (Peace's case)", async () => {
  const { hs, send } = setup();
  const first = await send({ url: POST_ACTIVITY, text: TEXT });
  const again = await send({ url: POST_UGC });
  assert.equal(again.body.status, "duplicate");
  assert.equal(again.body.dealId, first.body.dealId);
  assert.match(again.body.message, /same post as a recent capture/);
  assert.equal(hs.all("deals").length, 1);
});

test("link-only capture is filled in when the same post arrives with its other ID", async () => {
  const { hs, send } = setup();
  const first = await send({ url: POST_UGC });
  const later = await send({ url: POST_ACTIVITY, text: TEXT });
  assert.equal(later.body.status, "updated");
  assert.equal(later.body.dealId, first.body.dealId);
  assert.equal(hs.all("deals")[0].properties.pipeline_error, "");
  assert.equal(hs.all("deals")[0].properties.description, TEXT);
});

test("same poster, same text with different wording around it is still a duplicate", async () => {
  const { hs, send } = setup();
  await send({ url: POST_ACTIVITY, text: TEXT });
  const again = await send({ url: POST_UGC, text: `${TEXT} #hiring #remote` });
  assert.equal(again.body.status, "duplicate");
  assert.equal(hs.all("deals").length, 1);
});

test("same poster, a genuinely different post (different text) makes a new deal", async () => {
  const { hs, send } = setup();
  await send({ url: POST_ACTIVITY, text: TEXT });
  const other = await send({ url: POST_UGC, text: "Also hiring a Lifecycle Marketing Manager in Berlin, on-site, five days a week." });
  assert.equal(other.body.status, "created");
  assert.equal(hs.all("deals").length, 2);
  assert.equal(hs.all("contacts").length, 1);
});

test("same poster after more than 14 days is treated as a new post", async () => {
  const { hs, send } = setup();
  await send({ url: POST_ACTIVITY, text: TEXT });
  const later = Date.now() + 15 * 24 * 60 * 60 * 1000;
  hs.state.now = () => later;
  const RealNow = Date.now;
  Date.now = () => later;
  try {
    const again = await send({ url: POST_UGC });
    assert.equal(again.body.status, "created");
  } finally {
    Date.now = RealNow;
  }
});

test("similarText measures shared words", () => {
  assert.equal(similarText("Hiring a GTM Engineer", "hiring a gtm engineer!"), 1);
  assert.ok(similarText("Hiring a GTM Engineer remote", "We sell cheese in Paris") < 0.2);
  assert.equal(similarText("", "anything"), 0);
});
