// Minimal HubSpot REST client for the Worker (Service Key, Bearer token).
// Retries on rate limits and server errors; raises HubSpotError with
// HubSpot's own message so failures are loud and readable.

const BASE = "https://api.hubapi.com";

export class HubSpotError extends Error {
  constructor(status, message, category = "", path = "") {
    super(`HubSpot ${status} ${category} on ${path}: ${message}`.replace(/\s+/g, " ").trim());
    this.status = status;
    this.category = category;
  }
}

export class HubSpot {
  constructor(token, { fetchImpl = fetch, retries = 3, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
    if (!token) throw new Error("HUBSPOT_TOKEN is not set on the Worker.");
    this.token = token;
    this.fetch = fetchImpl;
    this.retries = retries;
    this.sleep = sleep;
  }

  async request(method, path, body) {
    for (let attempt = 0; ; attempt++) {
      const resp = await this.fetch(BASE + path, {
        method,
        headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if ((resp.status === 429 || resp.status >= 500) && attempt < this.retries) {
        const wait = Number(resp.headers.get("Retry-After")) || 2 ** attempt;
        await this.sleep(Math.min(wait, 10) * 1000);
        continue;
      }
      const text = await resp.text();
      const data = text ? safeJson(text) : null;
      if (resp.status >= 400) {
        throw new HubSpotError(resp.status, data?.message ?? text.slice(0, 300), data?.category ?? "", path);
      }
      return data;
    }
  }

  get(path) { return this.request("GET", path); }
  post(path, body) { return this.request("POST", path, body); }
  patch(path, body) { return this.request("PATCH", path, body); }
  put(path, body) { return this.request("PUT", path, body); }
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { message: text.slice(0, 300) };
  }
}
