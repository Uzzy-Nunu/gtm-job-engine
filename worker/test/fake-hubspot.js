// In-memory stand-in for the HubSpot API, served through a fake fetch().
// Implements only what the Worker uses. Made-up data only.

const STAGES = ["New", "Qualified", "Researched", "Ready for Review", "Approved", "Applied",
  "Followed Up", "Interviewing", "Offer", "Rejected", "Archived"];

export function createFakeHubSpot() {
  let nextId = 1001;
  const state = {
    objects: { deals: {}, contacts: {}, companies: {} },
    associations: new Set(),
    pipeline: { id: "default", label: "Job Applications", stages: STAGES.map((label, i) => ({ id: `stage${i}`, label })) },
    calls: [],
  };
  const reply = (status, body) => new Response(body === undefined ? "" : JSON.stringify(body), { status });
  const all = (obj) => Object.values(state.objects[obj]);

  async function fakeFetch(url, init = {}) {
    const method = init.method ?? "GET";
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : undefined;
    state.calls.push(`${method} ${path}`);
    const parts = path.split("/").filter(Boolean);

    if (method === "GET" && path === "/crm/v3/pipelines/deals") return reply(200, { results: [state.pipeline] });

    if (parts[0] === "crm" && parts[1] === "v3" && parts[2] === "objects") {
      const obj = parts[3];
      if (method === "POST" && parts[4] === "search") {
        const filters = body.filterGroups[0].filters;
        const hits = all(obj).filter((rec) => filters.every((f) =>
          String(rec.properties[f.propertyName] ?? "").toLowerCase() === String(f.value).toLowerCase()));
        return reply(200, { total: hits.length, results: hits.slice(0, body.limit ?? 10) });
      }
      if (method === "POST" && parts.length === 4) {
        if (obj === "deals" && all("deals").some((d) => d.properties.job_url === body.properties.job_url)) {
          return reply(409, { message: "duplicate job_url", category: "CONFLICT" });
        }
        const id = String(nextId++);
        state.objects[obj][id] = { id, properties: { ...body.properties } };
        return reply(201, state.objects[obj][id]);
      }
      if (method === "PATCH" && parts.length === 5) {
        const rec = state.objects[obj][parts[4]];
        if (!rec) return reply(404, { message: "not found" });
        Object.assign(rec.properties, body.properties);
        return reply(200, rec);
      }
    }
    if (method === "PUT" && parts[1] === "v4" && parts[5] === "associations") {
      const [from, fromId, to, toId] = [parts[3], parts[4], parts[7], parts[8]];
      state.associations.add(`${from}:${fromId}->${to}:${toId}`);
      state.associations.add(`${to}:${toId}->${from}:${fromId}`);
      return reply(200, { status: "COMPLETE" });
    }
    return reply(404, { message: `fake has no ${method} ${path}` });
  }

  return {
    fetch: fakeFetch,
    state,
    all,
    linked: (from, fromId, to) => [...state.associations]
      .filter((a) => a.startsWith(`${from}:${fromId}->${to}:`)).map((a) => a.split(":").pop()),
    stageLabel: (id) => state.pipeline.stages.find((s) => s.id === id)?.label,
  };
}
