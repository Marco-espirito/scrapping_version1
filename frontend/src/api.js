const BASE = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

async function http(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

export const api = {
  stats: () => http("/api/stats"),
  jobs: ({ status = "", minScore = 0, sort = "score" } = {}) => {
    const q = new URLSearchParams({ min_score: minScore, sort });
    if (status) q.set("status", status);
    return http(`/api/jobs?${q}`);
  },
  updateJob: (id, payload) =>
    http(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  collect: (payload) =>
    http("/api/collect", { method: "POST", body: JSON.stringify(payload) }),
  rank: () => http("/api/rank", { method: "POST" }),
};
