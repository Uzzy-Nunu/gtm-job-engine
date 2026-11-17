// Capture intake: one captured link becomes one HubSpot deal (PRD §10.1).
// JavaScript twin of src/intake.py for links sent from the paste form and
// the bookmarklet. Same rules:
//   - duplicate key = canonical LinkedIn post URL or normalised job URL
//   - a repeat never creates a second deal; if the first was waiting for
//     post text and text has now arrived, the text is added
//   - LinkedIn link + no text + no external job link = "NEEDS POST TEXT"
//   - poster contact from the URL (name marked unconfirmed), company from
//     the job link's domain, everything associated with the deal

import { HubSpotError } from "./hubspot.js";
import {
  URLError, companyDomain, findExternalJobLinks, isLinkedIn, normaliseUrl, parseLinkedInPost,
} from "./urls.js";

export const PIPELINE_LABEL = "Job Applications";
export const NEEDS_POST_TEXT = "NEEDS POST TEXT";
const LINKEDIN_PROPERTY = "hs_linkedin_url";
const MAX_TEXT = 60000;
const SAME_POSTER_WINDOW_DAYS = 14;
const SAME_TEXT_THRESHOLD = 0.6;   // share of words in common
const NOTES_MARKER = "\n\n--- Notes from Peace ---";

// LinkedIn gives one post two different IDs (the address bar shows an
// "activity" ID, "Copy link to post" often a "ugcPost" ID), so the URL alone
// can't always spot a repeat. A recent capture from the same poster counts
// as the same post when either side has no text yet, or the texts mostly match.
function words(text) {
  return new Set(String(text ?? "").toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []);
}

export function similarText(a, b) {
  const x = words(a);
  const y = words(b);
  if (!x.size || !y.size) return 0;
  let common = 0;
  for (const w of x) if (y.has(w)) common++;
  return common / Math.min(x.size, y.size);
}

function postText(description) {
  return String(description ?? "").split(NOTES_MARKER)[0].trim();
}

export function sinceMs(days, now = Date.now()) {
  return String(now - days * 24 * 60 * 60 * 1000);
}

const ATS_SOURCES = {
  "greenhouse.io": "Greenhouse", "lever.co": "Lever", "ashbyhq.com": "Ashby",
  "remoteok.com": "RemoteOK", "himalayas.app": "Himalayas", "weworkremotely.com": "WWR",
  "remotive.com": "Remotive", "jobicy.com": "Jobicy",
};

function sourceFor(url) {
  const host = new URL(url).hostname;
  for (const [domain, source] of Object.entries(ATS_SOURCES)) {
    if (host === domain || host.endsWith("." + domain)) return source;
  }
  return "Company Site";
}

function withNotes(text, notes) {
  return notes ? `${text}${NOTES_MARKER}\n${notes}`.trim() : text;
}


export class Intake {
  constructor(hubspot) {
    this.hs = hubspot;
    this.pipelineId = null;
    this.newStageId = null;
  }

  async submit({ url, text = "", notes = "" }) {
    try {
      return await this.#submit({ url, text, notes });
    } catch (e) {
      if (e instanceof URLError) return { status: "error", message: e.message, flags: [] };
      if (e instanceof HubSpotError) return { status: "error", message: `HubSpot error: ${e.message}`, flags: [] };
      throw e;
    }
  }

  async #resolvePipeline() {
    if (this.pipelineId) return;
    const data = await this.hs.get("/crm/v3/pipelines/deals");
    for (const p of data?.results ?? []) {
      if (p.label === PIPELINE_LABEL) {
        const stage = (p.stages ?? []).find((s) => s.label === "New");
        if (stage) {
          this.pipelineId = p.id;
          this.newStageId = stage.id;
          return;
        }
      }
    }
    throw new HubSpotError(404, `Pipeline '${PIPELINE_LABEL}' with a 'New' stage not found. Run Setup HubSpot first.`, "SETUP", "pipelines");
  }

  async #searchOne(obj, filters, properties) {
    const body = { filterGroups: [{ filters }], limit: 1 };
    if (properties) body.properties = properties;
    const found = await this.hs.post(`/crm/v3/objects/${obj}/search`, body);
    return found?.results?.[0] ?? null;
  }

  async #submit({ url, text, notes }) {
    await this.#resolvePipeline();
    text = String(text ?? "").trim().slice(0, MAX_TEXT);
    notes = String(notes ?? "").trim();

    const post = isLinkedIn(url) ? parseLinkedInPost(url) : null;
    const key = post ? post.canonicalUrl : normaliseUrl(url);
    const source = post ? "LinkedIn Post" : sourceFor(key);

    const existing = await this.#searchOne("deals",
      [{ propertyName: "job_url", operator: "EQ", value: key }], ["dealname", "pipeline_error", "description"]);
    if (existing) return this.#alreadyCaptured(existing, text, notes, "Already captured.");

    if (post?.profileUrl) {
      const twin = await this.#samePosterTwin(post, text);
      if (twin) {
        return this.#alreadyCaptured(twin, text, notes,
          "Looks like the same post as a recent capture from this poster (LinkedIn gives one post two different links).");
      }
    }

    const external = findExternalJobLinks(text);
    const applyUrl = external[0] ?? (post ? null : key);
    const companyId = await this.#upsertCompany(applyUrl);
    const contactId = post?.profileUrl ? await this.#upsertPoster(post) : null;

    const flags = [];
    let pipelineError = null;
    if (post && !text && !external.length) {
      flags.push(NEEDS_POST_TEXT);
      pipelineError = `${NEEDS_POST_TEXT}: open this deal in HubSpot and paste the LinkedIn post text into 'Deal description'.`;
    }
    if (post?.nameGuess) flags.push("POSTER NAME UNCONFIRMED");

    let dealname;
    if (post) dealname = `LinkedIn post by ${post.nameGuess ?? "unknown poster"} (${post.postId.slice(-6)})`;
    else dealname = `Job at ${companyDomain(key) ?? new URL(key).hostname}`;

    const properties = {
      dealname, pipeline: this.pipelineId, dealstage: this.newStageId, job_url: key, job_source: source,
    };
    if (applyUrl) properties.apply_url = applyUrl;
    const description = withNotes(text, notes);
    if (description) properties.description = description.slice(0, MAX_TEXT);
    if (pipelineError) properties.pipeline_error = pipelineError;

    let deal;
    try {
      deal = await this.hs.post("/crm/v3/objects/deals", { properties });
    } catch (e) {
      if (e instanceof HubSpotError && e.status === 409) {
        return { status: "duplicate", message: "Already captured (found while saving).", flags: [] };
      }
      throw e;
    }
    if (companyId) await this.#associate("deals", deal.id, "companies", companyId);
    if (contactId) {
      await this.#associate("deals", deal.id, "contacts", contactId);
      if (companyId) await this.#associate("contacts", contactId, "companies", companyId);
    }

    let message = "Saved to HubSpot as a new job.";
    if (flags.includes(NEEDS_POST_TEXT)) message += " No post text yet: paste it into the deal's description when you can.";
    return { status: "created", message, dealId: deal.id, flags };
  }

  async #alreadyCaptured(deal, text, notes, lead) {
    const waiting = String(deal.properties?.pipeline_error ?? "").startsWith(NEEDS_POST_TEXT);
    if (waiting && text) {
      await this.hs.patch(`/crm/v3/objects/deals/${deal.id}`, {
        properties: { description: withNotes(text, notes).slice(0, MAX_TEXT), pipeline_error: "" },
      });
      return { status: "updated", message: `${lead} Added the post text you sent.`, dealId: deal.id, flags: [] };
    }
    let message = `${lead} No new deal created.`;
    if (!text && !lead.startsWith("Already")) message += " If this is a different post, paste its text and save again.";
    return { status: "duplicate", message, dealId: deal.id, flags: [] };
  }

  async #samePosterTwin(post, text) {
    const contact = await this.#searchOne("contacts",
      [{ propertyName: LINKEDIN_PROPERTY, operator: "EQ", value: post.profileUrl }]);
    if (!contact) return null;
    const found = await this.hs.post("/crm/v3/objects/deals/search", {
      filterGroups: [{ filters: [
        { propertyName: "associations.contact", operator: "EQ", value: contact.id },
        { propertyName: "job_source", operator: "EQ", value: "LinkedIn Post" },
        { propertyName: "createdate", operator: "GTE", value: sinceMs(SAME_POSTER_WINDOW_DAYS) },
      ] }],
      properties: ["dealname", "pipeline_error", "description"],
      sorts: [{ propertyName: "createdate", direction: "DESCENDING" }],
      limit: 10,
    });
    for (const deal of found?.results ?? []) {
      const earlier = postText(deal.properties?.description);
      if (!text || !earlier || similarText(earlier, text) >= SAME_TEXT_THRESHOLD) return deal;
    }
    return null;
  }

  async #upsertCompany(applyUrl) {
    if (!applyUrl) return null;
    let domain = null;
    try {
      domain = companyDomain(applyUrl);
    } catch {
      domain = null;
    }
    if (!domain) return null;
    const found = await this.#searchOne("companies", [{ propertyName: "domain", operator: "EQ", value: domain }]);
    if (found) return found.id;
    const created = await this.hs.post("/crm/v3/objects/companies", { properties: { name: domain, domain } });
    return created.id;
  }

  async #upsertPoster(post) {
    const found = await this.#searchOne("contacts",
      [{ propertyName: LINKEDIN_PROPERTY, operator: "EQ", value: post.profileUrl }]);
    if (found) return found.id;
    const properties = { [LINKEDIN_PROPERTY]: post.profileUrl };
    if (post.nameGuess) {
      const [first, ...rest] = post.nameGuess.split(" ");
      properties.firstname = first;
      properties.lastname = `${rest.join(" ")} (unconfirmed)`.trim();
    }
    const created = await this.hs.post("/crm/v3/objects/contacts", { properties });
    return created.id;
  }

  async #associate(fromObj, fromId, toObj, toId) {
    await this.hs.put(`/crm/v4/objects/${fromObj}/${fromId}/associations/default/${toObj}/${toId}`);
  }
}
