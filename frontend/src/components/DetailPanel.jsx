import { useEffect, useState } from "react";
import { api } from "../api.js";
import StatusBadge from "./StatusBadge.jsx";
import SignalTrace from "./SignalTrace.jsx";

const CLASS_LABEL = {
  none: "No degradation signature",
  edfa: "Amplifier / EDFA aging",
  nli: "Nonlinear interference drift",
  ecl: "External-cavity laser aging",
  hard_cut: "Sudden fibre cut",
};

function StatBox({ label, value, note, tone = "" }) {
  return (
    <div className="detail-stat-box">
      <div className="detail-stat-label">{label}</div>
      <div className={`detail-stat-value ${tone}`}>{value}</div>
      <div className="detail-stat-note">{note}</div>
    </div>
  );
}

export default function DetailPanel({ linkId, rulMaeDays }) {
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!linkId) return;
    let cancelled = false;
    setDetail(null);
    setErr(null);
    api.linkDetail(linkId)
      .then((result) => { if (!cancelled) setDetail(result); })
      .catch((error) => { if (!cancelled) setErr(String(error.message || error)); });
    return () => { cancelled = true; };
  }, [linkId]);

  if (!linkId) {
    return (
      <div className="detail-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
          <path d="M3 12h4l2 8 4-16 2 8h6" />
        </svg>
        <div className="detail-empty-title">No link selected</div>
        <div className="detail-empty-sub">Choose a fibre link to inspect its signal history, forecast and recommended response.</div>
      </div>
    );
  }
  if (err) return <div className="error-banner">Couldn&rsquo;t load {linkId}: {err}</div>;
  if (!detail) return <div className="detail-empty"><div className="detail-empty-title mono">Loading {linkId}&hellip;</div></div>;

  const p = detail.prediction;
  const last = detail.trace?.at(-1) || {};
  const predictedClass = p.predicted_class || "none";
  const isEcl = predictedClass === "ecl";
  const isHard = predictedClass === "hard_cut";
  const ttf = p.predicted_ttf_days == null ? null : Math.max(0, Math.round(p.predicted_ttf_days));
  const hazard = Number.isFinite(p.hazard_score) ? Math.round(p.hazard_score) : null;
  const hazardTone = hazard >= 90 ? "alert" : hazard >= 70 ? "watch" : "normal";

  let nextAction = "Continue routine monitoring and compare the next telemetry readings with this baseline.";
  if (isHard || hazard >= 90) {
    nextAction = "Prioritise a route and environmental-risk inspection. Check for external excavation, weather exposure, and physical damage; use OTDR to localise suspected breaks.";
  } else if (ttf != null && ttf <= 14) {
    nextAction = "Schedule an urgent optical inspection. Verify connector cleanliness, splice loss, amplifier condition and the latest OTDR trace.";
  } else if (ttf != null && ttf <= 45) {
    nextAction = "Add this link to the maintenance watchlist and inspect the optical path during the next planned maintenance window.";
  } else if (p.status === "watch") {
    nextAction = "Review the environmental and signal trends. Keep the link under closer observation and confirm measurements at the equipment.";
  }

  return (
    <div>
      <div className="detail-head">
        <div className="detail-id">{detail.link_id}</div>
        <div className="detail-route">{detail.route_name}</div>
      </div>

      <div className="detail-status-row">
        <StatusBadge status={p.status} />
        <span className="detail-lifecycle">{detail.lifecycle === "ongoing" ? "Active monitoring" : "Resolved simulation incident"}</span>
      </div>

      <div className={`detail-rul-hero ${p.status}`}>
        <div className="detail-rul-kicker">ESTIMATED REMAINING USEFUL LIFE</div>
        <div className="detail-rul-value">{ttf == null ? (isHard ? "No countdown" : "Not available") : `${ttf} days`}</div>
        <div className="detail-rul-explain">
          {isHard
            ? "A sudden hard cut has no dependable telemetry countdown. Use the separate relative hazard indicator below."
            : ttf == null
              ? "The soft-failure model did not issue an estimate for this link."
              : `Track B estimate for a gradual soft-failure condition. Held-out model MAE: ${Number.isFinite(rulMaeDays) ? `${rulMaeDays.toFixed(1)} days` : "not available"}. MAE is an average test error, not an individual prediction interval.`}
        </div>
      </div>

      <div className="scope-panel">
        <div className="scope-header">
          <span className="scope-title">Signal quality · OSNR over time</span>
          <div className="scope-legend">
            <span className="scope-legend-item"><span className="scope-legend-swatch" style={{ background: "#f5a623" }} />18 dB warning</span>
            <span className="scope-legend-item"><span className="scope-legend-swatch" style={{ background: "#ff5d5d" }} />15 dB critical</span>
          </div>
        </div>
        <SignalTrace data={detail.trace} failureDay={detail.failure_day} />
      </div>

      <div className="detail-grid">
        <StatBox label="Predicted fault type" value={CLASS_LABEL[predictedClass] || predictedClass} note={`${(Number(p.class_confidence || 0) * 100).toFixed(0)}% classifier score · not a calibrated probability`} />
        <StatBox label="Hard-failure hazard rank" value={hazard == null ? "—" : `${hazard}th percentile`} tone={hazardTone} note="Track C · relative position within this cohort, not failure probability" />
        <StatBox label="Current OSNR" value={`${Number(last.osnr || 0).toFixed(2)} dB`} note="Optical signal-to-noise ratio" />
        <StatBox label="Laser bias current" value={`${Number(last.laser_current || 0).toFixed(2)} mA`} note={`Current OSNR breach run: ${p.breach_run_days ?? 0} consecutive days`} />
      </div>

      {isEcl && (
        <div className="callout">
          <b>Why this matters:</b> ECL aging can be partly hidden by automatic gain control, so OSNR may remain relatively stable while laser bias current changes. Check both signals rather than relying on OSNR alone.
        </div>
      )}
      {isHard && (
        <div className="callout warn">
          <b>No reliable countdown for sudden cuts.</b> The model treats hard cuts separately because they can occur without a gradual optical precursor. Track C provides a cohort-relative environmental hazard rank, not a date or a probability.
        </div>
      )}
      {!isHard && ttf != null && p.breach_run_days >= 3 && (
        <div className="callout warn">
          <b>Persistent signal warning:</b> OSNR has remained at or below the configured 18 dB warning threshold for {p.breach_run_days} consecutive observations. Verify this with the physical test equipment.
        </div>
      )}

      <div className="action-panel">
        <div className="action-panel-title"><span>↗</span> Recommended next action</div>
        <p>{nextAction}</p>
      </div>

      <div className="detail-section-label">Latest telemetry snapshot</div>
      <div className="telemetry-list">
        <div><span>Bit error rate</span><strong className="mono">{Number(last.ber || 0).toExponential(2)}</strong></div>
        <div><span>Receive power</span><strong className="mono">{Number(last.rx_power || 0).toFixed(2)} dBm</strong></div>
        <div><span>Temperature</span><strong className="mono">{Number(last.temp || 0).toFixed(1)} °C</strong></div>
        <div><span>Humidity</span><strong className="mono">{Number(last.humidity || 0).toFixed(1)}%</strong></div>
      </div>

      <div className="simulation-note">
        <b>Simulation transparency:</b> this demonstration uses generated telemetry. Validation truth label: {detail.true_failure_class || "not recorded"}. In a live deployment, this field would come from a confirmed maintenance or fault record.
      </div>
    </div>
  );
}
