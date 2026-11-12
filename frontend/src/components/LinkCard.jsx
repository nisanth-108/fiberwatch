import StatusBadge from "./StatusBadge.jsx";
import Sparkline from "./Sparkline.jsx";

function remainingLife(link) {
  if (link.predicted_ttf_days == null) {
    return link.predicted_class === "hard_cut" ? "No countdown" : "Not estimated";
  }
  return `${Math.max(0, Math.round(link.predicted_ttf_days))} days`;
}

export default function LinkCard({ link, selected, onClick }) {
  const hazard = Number.isFinite(link.hazard_score) ? Math.round(link.hazard_score) : null;
  return (
    <button
      type="button"
      className={`link-card status-${link.status}${selected ? " selected" : ""}`}
      onClick={onClick}
      aria-pressed={selected}
    >
      <div className="link-card-top">
        <div>
          <div className="link-id">{link.link_id}</div>
          <div className="link-route">{link.route_name}</div>
        </div>
        <StatusBadge status={link.status} />
      </div>

      <div className="link-card-rul">
        <div>
          <div className="rul-label">ESTIMATED REMAINING LIFE</div>
          <div className={`rul-value ${link.status}`}>{remainingLife(link)}</div>
        </div>
        {link.predicted_ttf_days != null && <div className="rul-chip">TRACK B</div>}
      </div>

      <div className="link-card-metrics">
        <div className="mini-metric">
          <div className="mini-metric-value mono">{Number(link.last_osnr).toFixed(1)} dB</div>
          <div className="mini-metric-label">Current OSNR</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric-value mono">{hazard == null ? "—" : `${hazard}th`}</div>
          <div className="mini-metric-label">Hazard percentile</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric-value mono">{link.breach_run_days ?? 0}d</div>
          <div className="mini-metric-label">Alarm duration</div>
        </div>
      </div>

      <Sparkline trace={link.sparkline} status={link.status} />
      <div className="card-open-hint">Select to inspect link <span>↗</span></div>
    </button>
  );
}
