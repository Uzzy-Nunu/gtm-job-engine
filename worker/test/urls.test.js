// Same shared fixtures as tests/test_urls.py, so Python and the Worker agree.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  URLError, companyDomain, findExternalJobLinks, normaliseUrl, parseLinkedInPost,
} from "../src/urls.js";

const CASES = JSON.parse(readFileSync(new URL("../../tests/fixtures/linkedin_urls.json", import.meta.url), "utf8"));

for (const c of CASES.valid) {
  test(`parses LinkedIn post ${c.post_id}`, () => {
    const post = parseLinkedInPost(c.url);
    assert.equal(post.postId, c.post_id);
    assert.equal(post.urnType, c.urn_type);
    assert.equal(post.canonicalUrl, c.canonical_url);
    assert.equal(post.authorSlug, c.author_slug);
    assert.equal(post.profileUrl, c.profile_url);
    assert.equal(post.nameGuess, c.name_guess);
  });
}

for (const c of CASES.invalid) {
  test(`rejects ${c.url.trim() || "blank"} with a helpful error`, () => {
    assert.throws(() => parseLinkedInPost(c.url), (e) => e instanceof URLError && e.message.includes(c.error_contains));
  });
}

for (const [raw, expected] of CASES.normalise) {
  test(`normalises ${raw}`, () => assert.equal(normaliseUrl(raw), expected));
}

test("different link styles for one post give one key", () => {
  assert.equal(normaliseUrl(CASES.valid[0].url),
    normaliseUrl("https://www.linkedin.com/feed/update/urn:li:activity:7390000000000000001"));
});

test("finds external job links and skips LinkedIn", () => {
  const text = "We're hiring! Apply: https://boards.greenhouse.io/samplecorp/jobs/123?gh_src=li. " +
    "More at https://www.linkedin.com/company/samplecorp and https://samplecorp.example/careers/gtm.";
  assert.deepEqual(findExternalJobLinks(text), [
    "https://boards.greenhouse.io/samplecorp/jobs/123",
    "https://samplecorp.example/careers/gtm",
  ]);
});

test("company domain", () => {
  assert.equal(companyDomain("https://careers.samplecorp.example/jobs/1"), "samplecorp.example");
  assert.equal(companyDomain("https://boards.greenhouse.io/samplecorp/jobs/1"), null);
  assert.equal(companyDomain("https://www.demo.example/jobs"), "demo.example");
});
