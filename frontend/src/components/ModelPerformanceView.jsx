const FEATURE_LABEL = {
  osnr_roll_mean: "OSNR roll. mean", osnr_roll_std: "OSNR roll. std",
  osnr_now: "OSNR (current)", osnr_velocity: "OSNR velocity", osnr_acceleration: "OSNR accel.",
  link_age_days: "Link age", laser_current_ma: "Laser current", laser_current_velocity: "Laser I velocity",
  temp_c: "Temperature", humidity_pct: "Humidity", precip_7d_sum: "Precip (7d)", wind_kmh: "Wind",
};
for (let i = 1; i <= 10; i++) FEATURE_LABEL[`osnr_lag_${i}`] = `OSNR lag-${i}`;

const COVARIATE_LABEL = { avg_temp: "Avg. temperature", avg_humidity: "Avg. humidity", avg_precip: "Avg. precipitation", avg_wind: "Avg. wind speed" };

function FeatureBars({ importances = {} }) {
  const entries = Object.entries(importances || {});
  const max = Math.max(0.000001, ...entries.map(([, value]) => Number(value) || 0));
  return (
    <div style={{ marginTop: 10 }}>
      {entries.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <span className="bar-label">{FEATURE_LABEL[k] || k}</span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></div>
        </div>
      ))}
    </div>
  );
}

function HazardCI({ ratios, ci }) {
  const DOMAIN = 4; // display clamp
  const pct = (v) => `${Math.min(100, Math.max(0, (v / DOMAIN) * 100))}%`;
  return (
    <div style={{ marginTop: 12 }}>
      <div className="ci-bar-label"><span /><span className="val" style={{ color: "var(--text-tertiary)" }}>HR=1 no-effect line</span></div>
      {Object.entries(ratios).map(([k, v]) => {
        const [lo, hi] = ci[k];
        const insignificant = lo <= 1 && hi >= 1;
        return (
          <div className="ci-bar-wrap" key={k}>
            <div className="ci-bar-label">
              <span className="name">{COVARIATE_LABEL[k] || k}</span>
              <span className="val">{v.toFixed(2)} <span style={{ color: "var(--text-tertiary)" }}>[{lo.toFixed(2)}, {hi.toFixed(2)}]</span></span>
            </div>
            <div className="ci-track">
              <div className="axis" />
              <div className="zero-line" style={{ left: pct(1) }} />
              <div className="ci-range" style={{ left: pct(Math.min(lo, DOMAIN)), width: `calc(${pct(Math.min(hi, DOMAIN))} - ${pct(Math.min(lo, DOMAIN))})` }} />
              <div className={`ci-point${insignificant ? " insignificant" : ""}`} style={{ left: pct(v) }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function ModelPerformanceView({ info }) {
  const a = info.track_a_classifier || {}, b = info.track_b_ttf_regressor || {}, c = info.track_c_hazard || {};
  const sources = info.model_sources || {};
  const sourceName = (key) => ({
    demo_labelled_data: "Demo-labelled telemetry",
    hardware_labelled_data: "Hardware-labelled telemetry",
    ingested_labelled_data: "Hardware / manual labelled telemetry",
    mixed_demo_and_ingested_data: "Mixed demo + ingested data",
  }[sources[key]] || "Simulation baseline");
  return (
    <div className="content">
      <div className="section-head">
        <div>
          <div className="section-title">Model performance</div>
          <div className="section-hint">Model sources: A — {sourceName("A")} · B — {sourceName("B")} · C — {sourceName("C")}</div>
        </div>
      </div>

      <div className="panel-grid">
        <div className="card">
          <div className="card-title"><span className="track-tag">TRACK B</span>Soft-failure time-to-failure</div>
          <div className="card-subtitle">Random Forest regressor · {sourceName("B")}</div>
          <div className="hero-stat">
            <span className="hero-stat-num good">{b.mae_days_soft_only == null ? "—" : `${b.mae_days_soft_only}d`}</span>
            <span className="hero-stat-arrow">Held-out MAE, soft failures only</span>
          </div>
          {b.mae_days_with_hard_cuts != null ? <div className="hero-stat">
            <span className="hero-stat-num bad">{b.mae_days_with_hard_cuts}d</span>
            <span className="hero-stat-arrow">MAE if hard-cuts are included ({b.degradation_factor}&times; worse)</span>
          </div> : <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.6, marginTop: 10 }}>This live-trained version is evaluated on confirmed soft-failure links only. Hard cuts and censored links are excluded from its RUL target.</p>}
          <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.6, marginTop: 10 }}>{b.note || b.target || "The MAE is measured on held-out link histories; it is not an individual prediction interval."}</p>
          <FeatureBars importances={b.top_features} />
        </div>

        <div className="card">
          <div className="card-title"><span className="track-tag">TRACK A</span>Fault-type classifier</div>
          <div className="card-subtitle">Random Forest · {(a.classes || []).length} classes · {sourceName("A")}</div>
          <div className="metric-row"><span className="metric-row-label">Macro F1</span><span className="metric-row-value">{a.macro_f1 ?? "—"}</span></div>
          <div className="metric-row"><span className="metric-row-label">Train / test rows</span><span className="metric-row-value">{Number(a.n_train || 0).toLocaleString()} / {Number(a.n_test || 0).toLocaleString()}</span></div>
          <div className="metric-row"><span className="metric-row-label">Classes</span><span className="metric-row-value" style={{ fontSize: 11 }}>{(a.classes || []).join(", ") || "—"}</span></div>
          <FeatureBars importances={a.top_features} />
        </div>

        <div className="card">
          <div className="card-title"><span className="track-tag">TRACK C</span>Hard-failure hazard</div>
          <div className="card-subtitle">Cox Proportional Hazards (lifelines) · {sourceName("C")}</div>
          <div className="metric-row"><span className="metric-row-label">Concordance index</span><span className="metric-row-value">{c.concordance_index ?? c.concordance_index_fit ?? "—"}</span></div>
          <div className="metric-row"><span className="metric-row-label">Links / events</span><span className="metric-row-value">{c.n_links ?? "—"} / {c.n_events ?? c.hard_cut_events ?? "—"}</span></div>
          {c.hazard_ratios && c.hazard_ratio_95ci ? <HazardCI ratios={c.hazard_ratios} ci={c.hazard_ratio_95ci} /> : <p className="footnote">Hazard ratios and confidence intervals become available after the survival model has enough labelled hard-cut and censored link histories.</p>}
          <p className="footnote">{c.evaluation || `The 95% intervals should be interpreted with the available number of confirmed events (${c.n_events ?? "—"}); additional labelled outcomes improve precision.`}</p>
        </div>
      </div>
    </div>
  );
}
