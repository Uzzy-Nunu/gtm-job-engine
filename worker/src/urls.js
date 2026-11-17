// URL helpers for capture (PRD §10.1 IN-1c, IN-2, IN-4).
// JavaScript twin of src/urls.py. Both are tested against
// tests/fixtures/linkedin_urls.json so they always agree.
// Works on the URL text only: nothing is fetched, LinkedIn is never contacted.

export class URLError extends Error {}

const TRACKING_PARAMS = new Set([
  "ref", "refid", "referrer", "source", "src", "trk", "trkinfo", "trackingid",
  "gh_src", "gh_jid_src", "lever-source", "lever-origin", "lever-via",
  "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
  "fbclid", "gclid", "mc_cid", "mc_eid", "rcm", "lipi", "originalsubdomain",
]);

const LINKEDIN_HOSTS = new Set(["linkedin.com", "www.linkedin.com", "m.linkedin.com", "lnkd.in"]);
const POST_ID = /-(activity|ugcPost|share)-(\d{15,25})/i;
const URN = /urn:li:(activity|ugcPost|share):(\d{15,25})/i;
const URL_IN_TEXT = /https?:\/\/[^\s<>"')\]]+/gi;
const URN_TYPES = { activity: "activity", ugcpost: "ugcPost", share: "share" };

const ATS_HOSTS = [
  "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com",
  "bamboohr.com", "recruitee.com", "breezy.hr", "teamtailor.com", "personio.de",
  "personio.com", "remoteok.com", "himalayas.app", "weworkremotely.com",
  "wellfound.com", "remotive.com", "jobicy.com",
];

function cleanInput(raw) {
  let url = String(raw ?? "").trim().replace(/^[<>"']+|[<>"']+$/g, "");
  if (!url) throw new URLError("Please paste a link.");
  if (!/^https?:\/\//i.test(url)) url = "https://" + url;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new URLError(`That doesn't look like a web link: ${url}`);
  }
  if (!parsed.hostname.includes(".")) throw new URLError(`That doesn't look like a web link: ${url}`);
  return parsed;
}

function host(parsed) {
  return parsed.hostname.toLowerCase();
}

export function isLinkedIn(raw) {
  let parsed;
  try {
    parsed = cleanInput(raw);
  } catch {
    return false;
  }
  const h = host(parsed);
  return LINKEDIN_HOSTS.has(h) || h.endsWith(".linkedin.com");
}

function nameFromSlug(slug) {
  const words = slug.split("-").filter(Boolean);
  while (words.length && /\d/.test(words[words.length - 1])) words.pop();
  const kept = words.filter((w) => !/\d/.test(w));
  if (!kept.length) return null;
  return kept.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(" ");
}

export function parseLinkedInPost(raw) {
  const parsed = cleanInput(raw);
  const h = host(parsed);
  if (h === "lnkd.in") {
    throw new URLError("Short lnkd.in links can't be read without visiting LinkedIn. " +
      "In the LinkedIn app, use '...' > 'Copy link to post' instead.");
  }
  if (!(LINKEDIN_HOSTS.has(h) || h.endsWith(".linkedin.com"))) throw new URLError("This is not a LinkedIn link.");

  const path = decodeURIComponent(parsed.pathname);
  let authorSlug = null;
  let match = null;
  const posts = path.match(/\/posts\/([^/?#]+)/);
  if (posts) {
    const segment = posts[1];
    match = segment.match(POST_ID);
    if (segment.includes("_")) {
      const candidate = segment.split("_", 1)[0].toLowerCase();
      if (/^[a-z0-9-]{2,100}$/.test(candidate)) authorSlug = candidate;
    }
  } else {
    match = path.match(URN) || decodeURIComponent(parsed.href).match(URN);
  }

  if (!match) {
    if (path.includes("/jobs/")) {
      throw new URLError("LinkedIn job pages aren't supported (we never open LinkedIn). " +
        "Paste the hiring post link, or the job's link on the company site.");
    }
    throw new URLError("Couldn't find a post ID in this LinkedIn link. " +
      "Use '...' > 'Copy link to post' on the post.");
  }

  const urnType = URN_TYPES[match[1].toLowerCase()];
  const postId = match[2];
  return {
    postId,
    urnType,
    canonicalUrl: `https://www.linkedin.com/feed/update/urn:li:${urnType}:${postId}`,
    authorSlug,
    profileUrl: authorSlug ? `https://www.linkedin.com/in/${authorSlug}` : null,
    nameGuess: authorSlug ? nameFromSlug(authorSlug) : null,
  };
}

export function normaliseUrl(raw) {
  const parsed = cleanInput(raw);
  if (isLinkedIn(parsed.href)) return parseLinkedInPost(parsed.href).canonicalUrl;
  let h = host(parsed);
  if (h.startsWith("www.")) h = h.slice(4);
  if (parsed.port && !["80", "443"].includes(parsed.port)) h = `${h}:${parsed.port}`;
  const query = [...parsed.searchParams.entries()]
    .filter(([k, v]) => v !== "" && !TRACKING_PARAMS.has(k.toLowerCase()) && !k.toLowerCase().startsWith("utm_"))
    .sort(([a, av], [b, bv]) => (a < b ? -1 : a > b ? 1 : av < bv ? -1 : av > bv ? 1 : 0));
  const path = parsed.pathname.replace(/\/{2,}/g, "/").replace(/\/+$/, "");
  const qs = query.length ? "?" + new URLSearchParams(query).toString() : "";
  return `https://${h}${path}${qs}`;
}

export function findExternalJobLinks(text) {
  const found = [];
  for (const raw of String(text ?? "").match(URL_IN_TEXT) || []) {
    const trimmed = raw.replace(/[.,;:!?]+$/, "");
    if (isLinkedIn(trimmed)) continue;
    let url;
    try {
      url = normaliseUrl(trimmed);
    } catch {
      continue;
    }
    if (!found.includes(url)) found.push(url);
  }
  return found;
}

export function companyDomain(raw) {
  let h = new URL(normaliseUrl(raw)).hostname.toLowerCase();
  if (h.startsWith("www.")) h = h.slice(4);
  if (ATS_HOSTS.some((a) => h === a || h.endsWith("." + a))) return null;
  for (const prefix of ["jobs.", "careers.", "apply.", "boards."]) {
    if (h.startsWith(prefix)) h = h.slice(prefix.length);
  }
  return h || null;
}
