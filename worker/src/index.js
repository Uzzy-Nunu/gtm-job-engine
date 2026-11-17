// GTM Job Engine capture Worker (PRD §10.1 IN-1, IN-1b, IN-2).
//
//   GET  /add          paste-a-link form (phone or desktop)
//   GET  /bookmarklet  install page for the capture button
//   POST /capture      JSON {url, text?, notes?} + header X-Capture-Secret
//   GET  /health       "ok"
//
// Secrets (set by the Deploy Worker workflow from GitHub Secrets):
//   HUBSPOT_TOKEN, CAPTURE_SECRET

import { HubSpot } from "./hubspot.js";
import { Intake } from "./intake.js";
import { addPage, bookmarkletPage } from "./pages.js";

const MAX_BODY = 100_000;

function securityHeaders(nonce) {
  const h = {
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
  };
  if (nonce) {
    h["Content-Security-Policy"] =
      `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; ` +
      "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'";
  }
  return h;
}

function html(body, nonce) {
  return new Response(body, { headers: { "Content-Type": "text/html; charset=utf-8", ...securityHeaders(nonce) } });
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...securityHeaders() },
  });
}

// Constant-time comparison so the key can't be guessed from response timing.
export function sameSecret(given, expected) {
  const enc = new TextEncoder();
  const a = enc.encode(String(given ?? ""));
  const b = enc.encode(String(expected ?? ""));
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a[i] ?? 0) ^ (b[i] ?? 0);
  return diff === 0;
}

async function capture(request, env, deps) {
  const secret = env.CAPTURE_SECRET;
  if (!secret || secret.length < 16) {
    return json({ status: "error", message: "The Worker's CAPTURE_SECRET isn't set up (16+ characters needed)." }, 500);
  }
  if (!sameSecret(request.headers.get("X-Capture-Secret"), secret)) {
    return json({ status: "error", message: "Access key isn't right." }, 401);
  }
  const raw = await request.text();
  if (raw.length > MAX_BODY) return json({ status: "error", message: "That's too much text (100 KB max)." }, 413);
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return json({ status: "error", message: "Request wasn't valid JSON." }, 400);
  }
  if (typeof payload?.url !== "string" || !payload.url.trim()) {
    return json({ status: "error", message: "Please paste a link." }, 400);
  }

  const hubspot = new HubSpot(env.HUBSPOT_TOKEN, deps);
  const result = await new Intake(hubspot).submit({
    url: payload.url, text: String(payload.text ?? ""), notes: String(payload.notes ?? ""),
  });
  if (result.status === "error") {
    // Logged without the post text or secrets (visible in Cloudflare's logs).
    console.error("capture failed:", result.message);
  }
  return json(result, result.status === "error" ? 422 : 200);
}

export async function handle(request, env, deps = {}) {
  const url = new URL(request.url);
  const nonce = crypto.randomUUID().replace(/-/g, "");
  try {
    if (request.method === "GET" && url.pathname === "/") return Response.redirect(`${url.origin}/add`, 302);
    if (request.method === "GET" && url.pathname === "/add") return html(addPage(nonce), nonce);
    if (request.method === "GET" && url.pathname === "/bookmarklet") return html(bookmarkletPage(url.origin, nonce), nonce);
    if (request.method === "GET" && url.pathname === "/health") return new Response("ok");
    if (request.method === "POST" && url.pathname === "/capture") return await capture(request, env, deps);
    return json({ status: "error", message: "Not found." }, 404);
  } catch (e) {
    console.error("unexpected error:", e?.message ?? e);
    return json({ status: "error", message: "Something went wrong on the server. Please try again." }, 500);
  }
}

export default {
  fetch: (request, env) => handle(request, env),
};
