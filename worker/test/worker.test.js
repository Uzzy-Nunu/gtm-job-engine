// Worker tests: M3 acceptance criteria (PRD §17) through the real request
// handler, plus security checks. Fake HubSpot, made-up data only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { handle, sameSecret } from "../src/index.js";
import { bookmarkletCode } from "../src/pages.js";
import { createFakeHubSpot } from "./fake-hubspot.js";

const SECRET = "test-secret-0123456789";
const ENV = { CAPTURE_SECRET: SECRET, HUBSPOT_TOKEN: "fake-token" };
const ORIGIN = "https://capture.example.workers.dev";
const POST = "https://www.linkedin.com/posts/jane-doe-123_hiring-gtm-activity-7390000000000000001-AbCd?utm_source=share";
const SAME_POST = "https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001/";
const TEXT = "We're hiring a GTM Engineer, remote worldwide. Python, Clay, HubSpot.";

function setup() {
  const hs = createFakeHubSpot();
  const send = async (payload, { secret = SECRET, env = ENV } = {}) => {
    const req = new Request(`${ORIGIN}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Capture-Secret": secret },
      body: typeof payload === "string" ? payload : JSON.stringify(payload),
    });
    const resp = await handle(req, env, { fetchImpl: hs.fetch, sleep: async () => {} });
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
