const BASE = "/api";

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  health: () => get("/health"),
  links: () => get("/links"),
  linkDetail: (id) => get(`/links/${id}`),
  alerts: () => get("/alerts"),
  analytics: () => get("/analytics"),
  liveLinks: () => get("/live/links"),
  liveLinkDetail: (id) => get(`/live/links/${encodeURIComponent(id)}`),
  liveSummary: () => get("/live/summary"),
  liveTraining: () => get("/live/training"),
  ingestTelemetry: async (payload) => {
    const res = await fetch(`${BASE}/live/telemetry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.detail || "telemetry ingestion failed"); }
    return res.json();
  },
  saveLiveLabel: async (payload) => {
    const res = await fetch(`${BASE}/live/labels`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.detail || "saving outcome label failed"); }
    return res.json();
  },
  trainLiveModels: async (source = "ingested") => {
    const res = await fetch(`${BASE}/live/train?source=${encodeURIComponent(source)}`, { method: "POST" });
    if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.detail || "live training failed"); }
    return res.json();
  },
  seedLiveDemo: async () => {
    const res = await fetch(`${BASE}/live/seed-demo`, { method: "POST" });
    if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.detail || "demo seeding failed"); }
    return res.json();
  },
  modelInfo: () => get("/model-info"),
  realValidation: () => get("/real-validation"),
  regenerate: async () => {
    const res = await fetch(`${BASE}/regenerate`, { method: "POST" });
    if (!res.ok) throw new Error("regenerate failed");
    return res.json();
  },
};
