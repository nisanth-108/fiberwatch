const LABELS = { normal: "Normal", watch: "Watch", alert: "Alert" };

export default function StatusBadge({ status }) {
  return <span className={`badge status-${status}`}>{LABELS[status] || status}</span>;
}
