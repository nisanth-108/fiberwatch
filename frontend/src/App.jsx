import { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";
import MonitoringView from "./components/MonitoringView.jsx";
import ModelPerformanceView from "./components/ModelPerformanceView.jsx";
import HardwareValidationView from "./components/HardwareValidationView.jsx";
import LiveLinkView from "./components/LiveLinkView.jsx";

const TABS = [
  { id: "monitoring", label: "Monitoring" },
  { id: "live", label: "Live-Link" },
  { id: "models", label: "Model performance" },
  { id: "hardware", label: "Hardware validation" },
];

function BrandMark() {
  return (
    <div className="brand-mark">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M2 12c3-6 6-6 8 0s5 6 8 0" stroke="#4dd8c4" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="2" cy="12" r="1.4" fill="#4dd8c4" />
        <circle cx="22" cy="12" r="1.4" fill="#4dd8c4" />
      </svg>
    </div>
  );
}

function LoadingScreen({ label }) {
  return (
    <div className="loading-shell">
      <svg className="loading-trace" viewBox="0 0 220 40">
        <path d="M0 20 Q 20 4, 40 20 T 80 20 T 120 20 T 160 20 T 200 20 T 220 20"
          fill="none" stroke="#4dd8c4" strokeWidth="1.6">
          <animate attributeName="d" dur="1.6s" repeatCount="indefinite"
            values="
              M0 20 Q 20 4, 40 20 T 80 20 T 120 20 T 160 20 T 200 20 T 220 20;
              M0 20 Q 20 36, 40 20 T 80 20 T 120 20 T 160 20 T 200 20 T 220 20;
              M0 20 Q 20 4, 40 20 T 80 20 T 120 20 T 160 20 T 200 20 T 220 20" />
        </path>
      </svg>
      <div className="mono">{label}</div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("monitoring");
  const [links, setLinks] = useState(null);
  const [modelInfo, setModelInfo] = useState(null);
  const [hwData, setHwData] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [error, setError] = useState(null);
  const [regenerating, setRegenerating] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [l, m, h, a] = await Promise.all([api.links(), api.modelInfo(), api.realValidation(), api.analytics()]);
      setLinks(l); setModelInfo(m); setHwData(h); setAnalytics(a); setError(null);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        await api.health();
        if (!cancelled) loadAll();
      } catch {
        if (!cancelled) setTimeout(poll, 2500);
      }
    }
    poll();
    return () => { cancelled = true; };
  }, [loadAll]);

  async function handleRegenerate() {
    setRegenerating(true);
    try {
      await api.regenerate();
      await loadAll();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setRegenerating(false);
    }
  }

  const ready = links && modelInfo && hwData && analytics;
  const alertCount = ready ? links.filter((l) => l.lifecycle === "ongoing" && l.status === "alert").length : 0;
  const watchCount = ready ? links.filter((l) => l.lifecycle === "ongoing" && l.status === "watch").length : 0;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <BrandMark />
          <div>
            <div className="brand-name">FiberWatch</div>
            <div className="brand-sub">AIOps failure forecasting</div>
          </div>
        </div>

        {ready && (
          <div className="topbar-stats">
            <div className="stat">
              <div className="stat-value">{links.length}</div>
              <div className="stat-label">Links tracked</div>
            </div>
            <div className="stat">
              <div className="stat-value alert">{alertCount}</div>
              <div className="stat-label">Active alerts</div>
            </div>
            <div className="stat">
              <div className="stat-value watch">{watchCount}</div>
              <div className="stat-label">Watch</div>
            </div>
          </div>
        )}

        <div className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={`tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        <button className={`regen-btn${regenerating ? " spinning" : ""}`} onClick={handleRegenerate} disabled={regenerating}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4v6h6M20 20v-6h-6" />
            <path d="M4 10a8 8 0 0114-5M20 14a8 8 0 01-14 5" />
          </svg>
          {regenerating ? "Retraining\u2026" : "Regenerate"}
        </button>
      </div>

      {error && <div className="content"><div className="error-banner">{error} &mdash; is the backend running on :8000?</div></div>}

      {!ready && !error && <LoadingScreen label={links === null ? "training models\u2026 (first load can take ~30\u201350s)" : "loading\u2026"} />}

      {ready && tab === "monitoring" && <MonitoringView links={links} analytics={analytics} modelInfo={modelInfo} />}
      {ready && tab === "live" && <LiveLinkView onModelsChanged={loadAll} />}
      {ready && tab === "models" && <ModelPerformanceView info={modelInfo} />}
      {ready && tab === "hardware" && <HardwareValidationView data={hwData} />}
    </div>
  );
}
