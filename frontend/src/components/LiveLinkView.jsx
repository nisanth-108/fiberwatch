import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";

const FAULTS = [
  { value: "edfa", label: "EDFA degradation" },
  { value: "nli", label: "Nonlinear interference (NLI)" },
  { value: "ecl", label: "Laser / ECL aging" },
  { value: "hard_cut", label: "Hard cut / physical break" },
  { value: "none", label: "No failure observed yet (censored)" },
];

function Metric({ label, value, note, tone = "" }) {
  return <div className={`live-metric ${tone}`}><span>{label}</span><strong className="mono">{value}</strong><small>{note}</small></div>;
}

function StatusPill({ status }) {
  const text = status === "critical" ? "Critical" : status === "watch" ? "Watch" : "Healthy";
  return <span className={`live-status ${status || "normal"}`}>{text}</span>;
}

function fmt(value, decimals = 2) {
  return value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(decimals);
}

export default function LiveLinkView({ onModelsChanged }) {
  const [links, setLinks] = useState([]);
  const [summary, setSummary] = useState(null);
  const [training, setTraining] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showDeviceHelp, setShowDeviceHelp] = useState(false);
  const [trainingMode, setTrainingMode] = useState("demo");

  const [reading, setReading] = useState({
    link_id: "LAB-FL-01", route_name: "Optical lab bench", osnr_db: "22.8",
    laser_current_ma: "65.1", ber: "1e-9", rx_power_dbm: "-11.8",
    temp_c: "28", humidity_pct: "60", precip_mm: "0", wind_kmh: "0",
  });
  const [label, setLabel] = useState({ failure_class: "none", outcome_at: "", notes: "" });

  const refresh = useCallback(async (quiet = false) => {
    try {
      const [l, s, t] = await Promise.all([api.liveLinks(), api.liveSummary(), api.liveTraining()]);
      setLinks(l); setSummary(s); setTraining(t);
      setSelectedId((current) => current && l.some((x) => x.link_id === current) ? current : (l[0]?.link_id || ""));
      setError("");
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(() => refresh(true), 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    let cancelled = false;
    api.liveLinkDetail(selectedId).then((value) => { if (!cancelled) setDetail(value); })
      .catch((e) => { if (!cancelled) setError(e.message || String(e)); });
    return () => { cancelled = true; };
  }, [selectedId, links.length, summary?.samples]);

  const selected = useMemo(() => links.find((x) => x.link_id === selectedId), [links, selectedId]);
  const chartData = useMemo(() => (detail?.readings || []).map((r, index) => ({
    index: index + 1,
    time: new Date(r.observed_at).toLocaleString(),
    osnr: Number(r.osnr_db),
  })), [detail]);

  async function seedDemo() {
    setBusy("demo"); setError(""); setNotice("");
    try {
      const result = await api.seedLiveDemo();
      setNotice(`Loaded ${result.links_imported} clearly labelled demo links into the Live-Link store.`);
      await refresh(true);
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(""); }
  }

  async function submitReading(event) {
    event.preventDefault(); setBusy("reading"); setError(""); setNotice("");
    try {
      const payload = Object.fromEntries(Object.entries(reading).map(([k, v]) => [k, ["link_id", "route_name"].includes(k) ? v : Number(v)]));
      payload.source = "manual";
      const result = await api.ingestTelemetry(payload);
      setSelectedId(result.link_id);
      setNotice(`Stored reading #${result.id} for ${result.link_id}.`);
      await refresh(true);
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(""); }
  }

  async function saveLabel(event) {
    event.preventDefault();
    if (!selectedId) return;
    const isCensored = label.failure_class === "none";
    setBusy("label"); setError(""); setNotice("");
    try {
      await api.saveLiveLabel({
        link_id: selectedId,
        failure_class: label.failure_class,
        outcome_status: isCensored ? "censored" : "resolved",
        outcome_at: isCensored ? null : new Date(label.outcome_at).toISOString(),
        notes: label.notes,
      });
      setNotice(`Outcome label saved for ${selectedId}. This link can now contribute to eligible model training.`);
      await refresh(true);
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(""); }
  }

  async function trainModels() {
    setBusy("train"); setError(""); setNotice("");
    try {
      const result = await api.trainLiveModels(trainingMode);
      const trained = (result.applied_tracks || []).join(", ") || "none yet";
      setNotice(`${result.message} Applied tracks: ${trained}. Review each track's eligibility below.`);
      await refresh(true);
      if (onModelsChanged) await onModelsChanged();
    } catch (e) { setError(e.message || String(e)); }
    finally { setBusy(""); }
  }

  return (
    <div className="content live-page">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">TELEMETRY INGESTION & MODEL LEARNING</div>
          <h1>Live-Link</h1>
          <p className="page-intro">Receive optical measurements, build link histories, confirm outcomes, and retrain the forecasting models from labelled field data.</p>
        </div>
        <div className="live-auto-refresh"><span className="pulse-dot" /> Refreshes every 5 seconds</div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="live-notice">{notice}</div>}

      <div className="live-metrics-grid">
        <Metric label="LINKS INGESTED" value={summary?.links ?? "—"} note="Distinct monitored routes" />
        <Metric label="TELEMETRY SAMPLES" value={(summary?.samples ?? 0).toLocaleString()} note="Persisted timestamped readings" />
        <Metric label="LABELLED LINKS" value={summary?.labelled_links ?? "—"} note={`${summary?.resolved_links ?? 0} resolved · ${summary?.censored_links ?? 0} censored`} />
        <Metric label="NEED ATTENTION" value={(summary?.critical_links ?? 0) + (summary?.watch_links ?? 0)} note={`${summary?.critical_links ?? 0} critical · ${summary?.watch_links ?? 0} watch`} tone="warn" />
      </div>

      <div className="live-grid-two">
        <section className="overview-panel live-panel">
          <div className="panel-heading-row">
            <div><div className="panel-heading">Connect a telemetry source</div><div className="panel-subheading">Use a device gateway, manual test reading, or clearly marked demo data.</div></div>
            <span className="live-source-chip">API READY</span>
          </div>
          <div className="live-actions-row">
            <button className="primary-action" onClick={seedDemo} disabled={!!busy}>{busy === "demo" ? "Loading demo fleet…" : "Load demo fleet"}</button>
            <button className="secondary-action" onClick={() => setShowDeviceHelp((v) => !v)}>{showDeviceHelp ? "Hide device API" : "Device integration guide"}</button>
          </div>
          {showDeviceHelp && (
            <div className="device-help">
              <strong>Device gateway endpoint</strong>
              <code>POST http://localhost:8000/api/live/telemetry</code>
              <pre>{`{
  "link_id": "LAB-FL-01",
  "observed_at": "2026-10-30T10:30:00Z",
  "osnr_db": 22.8,
  "laser_current_ma": 65.1,
  "ber": 1e-9,
  "rx_power_dbm": -11.8,
  "temp_c": 28,
  "humidity_pct": 60,
  "source": "hardware"
}`}</pre>
              <small>Send JSON from the instrument's supported API, a PC gateway, or an adapter. The endpoint does not directly communicate with an optical instrument by itself; the adapter must translate its readings into this schema.</small>
            </div>
          )}
          <div className="live-form-title">Add a manual measurement</div>
          <form className="live-reading-form" onSubmit={submitReading}>
            <label>Link ID<input value={reading.link_id} onChange={(e) => setReading({ ...reading, link_id: e.target.value })} required /></label>
            <label>Route / location<input value={reading.route_name} onChange={(e) => setReading({ ...reading, route_name: e.target.value })} /></label>
            <label>OSNR (dB)<input type="number" step="0.01" value={reading.osnr_db} onChange={(e) => setReading({ ...reading, osnr_db: e.target.value })} required /></label>
            <label>Laser current (mA)<input type="number" step="0.01" value={reading.laser_current_ma} onChange={(e) => setReading({ ...reading, laser_current_ma: e.target.value })} /></label>
            <label>BER<input value={reading.ber} onChange={(e) => setReading({ ...reading, ber: e.target.value })} /></label>
            <label>Rx power (dBm)<input type="number" step="0.01" value={reading.rx_power_dbm} onChange={(e) => setReading({ ...reading, rx_power_dbm: e.target.value })} /></label>
            <label>Temperature (°C)<input type="number" step="0.1" value={reading.temp_c} onChange={(e) => setReading({ ...reading, temp_c: e.target.value })} /></label>
            <label>Humidity (%)<input type="number" step="0.1" min="0" max="100" value={reading.humidity_pct} onChange={(e) => setReading({ ...reading, humidity_pct: e.target.value })} /></label>
            <button className="primary-action form-submit" type="submit" disabled={!!busy}>{busy === "reading" ? "Saving…" : "Store measurement"}</button>
          </form>
          <div className="panel-footnote">Manual entries are tagged <b>manual</b>. Only a connected instrument or its gateway should send <b>hardware</b> source records.</div>
        </section>

        <section className="overview-panel live-panel">
          <div className="panel-heading">Live-link inventory</div>
          <div className="panel-subheading">Latest received measurement and data freshness.</div>
          <div className="live-table-wrap">
            <table className="live-table">
              <thead><tr><th>Link</th><th>OSNR</th><th>Status</th><th>Samples</th><th>Source</th></tr></thead>
              <tbody>
                {links.map((link) => (
                  <tr key={link.link_id} className={selectedId === link.link_id ? "selected" : ""} onClick={() => setSelectedId(link.link_id)}>
                    <td><strong>{link.link_id}</strong><small>{link.route_name}</small></td>
                    <td className="mono">{fmt(link.osnr_db)} dB</td>
                    <td><StatusPill status={link.status} />{link.is_stale && <small className="stale-label">Stale</small>}</td>
                    <td className="mono">{link.sample_count}</td>
                    <td><small>{link.source || "—"}</small></td>
                  </tr>
                ))}
                {!links.length && <tr><td colSpan="5" className="empty-table">{loading ? "Loading telemetry…" : "No telemetry received yet. Add a reading or load the demo fleet."}</td></tr>}
              </tbody>
            </table>
          </div>
          {summary?.source_counts && <div className="source-breakdown">Sources: {Object.entries(summary.source_counts).map(([source, count]) => `${source}: ${count}`).join(" · ")}</div>}
        </section>
      </div>

      <div className="live-grid-two live-bottom-grid">
        <section className="overview-panel live-panel">
          <div className="panel-heading-row"><div><div className="panel-heading">Selected link · {selectedId || "—"}</div><div className="panel-subheading">Daily aggregation is used for model features to match the original model cadence.</div></div>{selected && <StatusPill status={selected.status} />}</div>
          {selected ? (
            <>
              <div className="live-signal-grid">
                <div><small>Latest OSNR</small><strong className="mono">{fmt(selected.osnr_db)} dB</strong></div>
                <div><small>Laser current</small><strong className="mono">{fmt(selected.laser_current_ma)} mA</strong></div>
                <div><small>BER</small><strong className="mono">{selected.ber == null ? "—" : Number(selected.ber).toExponential(2)}</strong></div>
                <div><small>Daily observations</small><strong className="mono">{selected.daily_observations}</strong></div>
                <div><small>Hard-cut hazard rank</small><strong className="mono">{selected.hard_failure_hazard_percentile == null ? "—" : `${selected.hard_failure_hazard_percentile}th`}</strong></div>
              </div>
              <div className="live-chart-title">OSNR history</div>
              <div className="live-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData} margin={{ top: 8, right: 14, left: 0, bottom: 3 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-soft)" />
                <XAxis dataKey="index" tick={{ fill: "var(--text-tertiary)", fontSize: 10 }} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--text-tertiary)", fontSize: 10 }} width={42} />
                <Tooltip labelFormatter={(v) => `Sample ${v}`} formatter={(v) => [`${Number(v).toFixed(2)} dB`, "OSNR"]} contentStyle={{ background: "var(--panel-raised)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 11 }} />
                <Line type="monotone" dataKey="osnr" stroke="#4dd8c4" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
              </LineChart></ResponsiveContainer></div>
              <div className="panel-footnote">Model prediction: {selected.prediction_ready ? `${selected.predicted_class || "unknown"}${selected.predicted_ttf_days != null ? ` · ${selected.predicted_ttf_days} estimated days to soft failure` : " · no RUL estimate"}` : "Not enough daily history yet (requires at least 11 consecutive daily observations)."}</div>
              <div className="panel-footnote">Prediction sources: classifier — {selected.classifier_source || "not yet available"}; RUL — {selected.rul_source || "not available"}; hard-cut rank — {selected.hazard_source || "not available"}. Hazard is a cohort-relative rank, not a failure probability.</div>
            </>
          ) : <div className="empty-inline">Select a link from the inventory to inspect its history.</div>}
        </section>

        <section className="overview-panel live-panel">
          <div className="panel-heading">Confirm an outcome for model training</div>
          <div className="panel-subheading">Training labels must come from a verified fault, maintenance report, or an explicitly censored observation.</div>
          <form className="label-form" onSubmit={saveLabel}>
            <label>Outcome / fault type<select value={label.failure_class} onChange={(e) => setLabel({ ...label, failure_class: e.target.value })}>{FAULTS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}</select></label>
            {label.failure_class !== "none" && <label>Confirmed failure time<input type="datetime-local" value={label.outcome_at} onChange={(e) => setLabel({ ...label, outcome_at: e.target.value })} required /></label>}
            <label>Maintenance / observation notes<textarea rows="3" value={label.notes} onChange={(e) => setLabel({ ...label, notes: e.target.value })} placeholder="e.g. OTDR confirmed a connector event; link repaired…" /></label>
            <button className="secondary-action full-width" type="submit" disabled={!selectedId || !!busy}>{busy === "label" ? "Saving label…" : `Save outcome for ${selectedId || "selected link"}`}</button>
          </form>
          <div className="training-divider" />
          <div className="panel-heading">Train models from Live-Link data</div>
          <div className="train-model-grid">
            {[["A", "Fault classifier"], ["B", "Remaining-life regressor"], ["C", "Hard-cut survival model"]].map(([id, name]) => {
              const modelStatus = training?.model_sources?.[id] && training.model_sources[id] !== "simulation_baseline" ? "Retrained from selected data" : "Simulation baseline";
              return <div key={id}><b>Track {id}</b><span>{name}</span><small>{modelStatus}</small></div>;
            })}
          </div>
          <button className="primary-action full-width" onClick={trainModels} disabled={!!busy || !(training?.labelled_links > 0)}>{busy === "train" ? "Training models…" : "Train from labelled Live-Link history"}</button>
          <div className="track-requirements">
            <b>Training rules</b>
            <span>Track A: multiple independently labelled links and fault classes.</span>
            <span>Track B: at least 5 confirmed soft-failure links; hard cuts and censored links are excluded.</span>
            <span>Track C: at least 5 confirmed hard cuts plus 5 censored links.</span>
          </div>
          <div className="panel-footnote">Only tracks meeting their data requirements are replaced. Otherwise, the existing model remains active. Demo data is kept separate unless you explicitly choose the mixed option.</div>
        </section>
      </div>
      <div className="live-disclaimer">Live-Link stores incoming measurements in a local SQLite database. Generated demo data is tagged separately. A model is only considered field-trained after it is trained on labelled field records; a raw telemetry stream alone cannot teach a supervised model what failure occurred.</div>
    </div>
  );
}
