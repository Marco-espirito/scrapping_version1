import { useEffect, useState, useCallback } from "react";
import { api } from "./api";

const STATUSES = [
  { key: "nouvelle", label: "Nouvelles", color: "#3b82f6" },
  { key: "a_postuler", label: "À postuler", color: "#f59e0b" },
  { key: "postulee", label: "Postulées", color: "#10b981" },
  { key: "refusee", label: "Refusées", color: "#ef4444" },
  { key: "ignoree", label: "Ignorées", color: "#6b7280" },
];

function scoreColor(s) {
  if (s >= 50) return "#10b981";
  if (s >= 25) return "#f59e0b";
  return "#9ca3af";
}

export default function App() {
  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState({ total: 0, by_status: {} });
  const [filter, setFilter] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [sort, setSort] = useState("score");
  const [loading, setLoading] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [collectionMessage, setCollectionMessage] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({ query: "développeur full stack", location: "Lyon", limit: 12, source: "indeed" });

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [j, st] = await Promise.all([
        api.jobs({ status: filter, minScore, sort }),
        api.stats(),
      ]);
      setJobs(j);
      setStats(st);
    } catch (e) {
      setError("API indisponible : " + e.message);
    } finally {
      setLoading(false);
    }
  }, [filter, minScore, sort]);

  useEffect(() => { refresh(); }, [refresh]);

  async function setStatus(id, status) {
    try {
      await api.updateJob(id, { status });
      refresh();
    } catch (e) {
      setError("Mise à jour impossible : " + e.message);
    }
  }

  async function runCollect() {
    setCollecting(true);
    setError("");
    setCollectionMessage("Envoi de la demande…");
    try {
      let r = await api.collect(form);
      if (r.task_id) {
        setCollectionMessage("En attente de l’agent local sur ton PC…");
        for (let attempt = 0; attempt < 300; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, 3000));
          r = await api.collectStatus(r.task_id);
          if (r.status === "running") {
            setCollectionMessage(`Collecte ${r.source} en cours sur ton PC…`);
          }
          if (r.status === "completed") break;
          if (r.status === "failed") throw new Error(r.error || "Échec de l’agent local");
        }
        if (r.status !== "completed") {
          throw new Error("Délai dépassé : vérifie que l’agent local est lancé");
        }
      }
      setCollectionMessage(
        `Terminé : ${r.scraped} offres, ${r.inserted} nouvelles, ${r.updated} déjà connues.`
      );
      refresh();
    } catch (e) {
      setCollectionMessage("");
      setError("Erreur collecte : " + e.message);
    } finally {
      setCollecting(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>🎯 JobApply <span className="muted">— {stats.total} offres en base</span></h1>
      </header>

      {error && (
        <div className="error" role="alert">
          <b>Un problème est survenu.</b> {error}
          <button onClick={refresh}>Réessayer</button>
        </div>
      )}

      {collectionMessage && (
        <div className="collection-status" role="status">{collectionMessage}</div>
      )}

      <section className="collect">
        <input value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} placeholder="Métier / mots-clés" />
        <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="Lieu" />
        <input type="number" value={form.limit} onChange={(e) => setForm({ ...form, limit: +e.target.value })} style={{ width: 70 }} />
        <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
          <option value="indeed">Indeed</option>
          <option value="glassdoor">Glassdoor</option>
        </select>
        <button className="primary" disabled={collecting} onClick={runCollect}>
          {collecting ? "Collecte en cours…" : `🔍 Scraper ${form.source === "glassdoor" ? "Glassdoor" : "Indeed"}`}
        </button>
        <button onClick={async () => { await api.rank(); refresh(); }}>♻️ Recalculer scores</button>
      </section>

      <nav className="tabs">
        <button className={filter === "" ? "on" : ""} onClick={() => setFilter("")}>
          Toutes ({stats.total})
        </button>
        {STATUSES.map((s) => (
          <button key={s.key} className={filter === s.key ? "on" : ""}
            onClick={() => setFilter(s.key)} style={{ "--c": s.color }}>
            {s.label} ({stats.by_status[s.key] || 0})
          </button>
        ))}
        <span className="spacer" />
        <label className="ctrl">Score min
          <input type="range" min="0" max="100" value={minScore}
            onChange={(e) => setMinScore(+e.target.value)} />
          <b>{minScore}</b>
        </label>
        <select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="score">Tri : score</option>
          <option value="date">Tri : date</option>
        </select>
      </nav>

      {loading ? <p className="muted">Chargement…</p> : (
        <ul className="jobs">
          {jobs.map((j) => (
            <li key={j.id} className="job">
              <div className="score" style={{ background: scoreColor(j.match_score) }}>
                {j.match_score.toFixed(0)}
              </div>
              <div className="body">
                <a href={j.url} target="_blank" rel="noreferrer" className="title">{j.title}</a>
                <div className="meta">
                  <span className={`src src-${j.source}`}>{j.source}</span>
                  <b>{j.company}</b> · {j.location} {j.salary && <span className="sal">· {j.salary}</span>}
                </div>
              </div>
              <div className="actions">
                <button onClick={() => setStatus(j.id, "a_postuler")}>⭐ À postuler</button>
                <button onClick={() => setStatus(j.id, "postulee")}>✅ Postulée</button>
                <button onClick={() => setStatus(j.id, "ignoree")}>🗑️ Ignorer</button>
              </div>
            </li>
          ))}
          {jobs.length === 0 && <p className="muted">Aucune offre pour ce filtre.</p>}
        </ul>
      )}
    </div>
  );
}
