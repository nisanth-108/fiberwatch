import { useEffect, useMemo, useState } from "react";
import LinkCard from "./LinkCard.jsx";
import DetailPanel from "./DetailPanel.jsx";
import NetworkMap from "./NetworkMap.jsx";

const FILTERS = [
  { id: "all", label: "All links" },
  { id: "alert", label: "Critical" },
  { id: "watch", label: "Watch" },
  { id: "normal", label: "Normal" },
];

function MetricCard({ label, value, note, tone = "default", icon }) {
  return (
    <div className={`overview-metric ${tone}`}>
      <div className="overview-metric-top">
        <span>{label}</span>
        <span className="metric-icon" aria-hidden="true">{icon}</span>
      </div>
      <div className="overview-metric-value mono">{value}</div>
      <div className="overview-metric-note">{note}</div>
    </div>
  );
}

function RiskDistribution({ counts, total }) {
  const segments = [
    { id: "normal", label: "Normal", color: "var(--status-normal)" },
    { id: "watch", label: "Watch", color: "var(--status-watch)" },
    { id: "alert", label: "Critical", color: "var(--status-alert)" },
  ];
  return (
    <section className="overview-panel distribution-panel">
      <div className="panel-heading-row">
        <div>
          <div className="panel-heading">Network risk distribution</div>
          <div className="panel-subheading">Current status across active links only</div>
        </div>
        <div className="panel-total mono">{total} <span>links</span></div>
      </div>
      <div className="distribution-track" role="img" aria-label={segments.map((s) => `${s.label}: ${counts[s.id]}`).join(", ")}>
        {segments.map((segment) => (
          <div key={segment.id} style={{ width: `${total ? (counts[segment.id] / total) * 100 : 0}%`, background: segment.color }} />
        ))}
      </div>
      <div className="distribution-legend">
        {segments.map((segment) => (
          <div className="distribution-item" key={segment.id}>
            <span className="legend-dot" style={{ background: segment.color }} />
            <span>{segment.label}</span>
            <strong className="mono">{counts[segment.id]}</strong>
            <small>{total ? Math.round((counts[segment.id] / total) * 100) : 0}%</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function RemainingLifeSummary({ links }) {
  const eligible = links.filter((link) => link.lifecycle === "ongoing" && link.predicted_ttf_days != null && link.predicted_class !== "hard_cut");
  const ranges = [
    { label: "0–14 days", min: 0, max: 14, tone: "alert" },
    { label: "15–45 days", min: 15, max: 45, tone: "watch" },
    { label: "46+ days", min: 46, max: Infinity, tone: "normal" },
  ];
  const counts = ranges.map((range) => eligible.filter((link) => {
    const days = Math.max(0, Number(link.predicted_ttf_days));
    return days >= range.min && days <= range.max;
  }).length);
  const maxCount = Math.max(1, ...counts);
  return (
    <section className="overview-panel rul-panel">
      <div className="panel-heading">Estimated remaining useful life</div>
      <div className="panel-subheading">Soft-failure links with a Track B estimate · active links only</div>
      {eligible.length ? (
        <div className="rul-bars">
          {ranges.map((range, index) => (
            <div className="rul-bar-row" key={range.label}>
              <span>{range.label}</span>
              <div className="rul-bar-track"><div className={`rul-bar-fill ${range.tone}`} style={{ width: `${(counts[index] / maxCount) * 100}%` }} /></div>
              <strong className="mono">{counts[index]}</strong>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-inline">No active soft-failure links currently have a remaining-life estimate.</div>
      )}
      <div className="panel-footnote">These are model estimates, not guaranteed countdowns. Sudden hard cuts do not receive an RUL estimate.</div>
    </section>
  );
}

export default function MonitoringView({ links, analytics, modelInfo }) {
  const [lifecycle, setLifecycle] = useState("ongoing");
  const [selected, setSelected] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");

  const counts = useMemo(() => {
    const active = links.filter((link) => link.lifecycle === "ongoing");
    const resolved = links.filter((link) => link.lifecycle === "resolved_incident");
    return {
      ongoing: active.length,
      resolved_incident: resolved.length,
      alert: active.filter((link) => link.status === "alert").length,
      watch: active.filter((link) => link.status === "watch").length,
      normal: active.filter((link) => link.status === "normal").length,
      resolvedAlert: resolved.filter((link) => link.status === "alert").length,
      resolvedWatch: resolved.filter((link) => link.status === "watch").length,
      resolvedNormal: resolved.filter((link) => link.status === "normal").length,
    };
  }, [links]);

  useEffect(() => {
    if (!selected && links.length) {
      const firstActive = links.find((link) => link.lifecycle === "ongoing");
      setSelected((firstActive || links[0]).link_id);
    }
  }, [links, selected]);

  const filtered = useMemo(() => links.filter((link) => {
    const matchesLifecycle = link.lifecycle === lifecycle;
    const matchesStatus = statusFilter === "all" || link.status === statusFilter;
    const q = search.trim().toLowerCase();
    const matchesSearch = !q || `${link.link_id} ${link.route_name}`.toLowerCase().includes(q);
    return matchesLifecycle && matchesStatus && matchesSearch;
  }), [links, lifecycle, statusFilter, search]);

  const activeLinks = links.filter((link) => link.lifecycle === "ongoing");
  const softRulLinks = activeLinks.filter((link) => link.predicted_ttf_days != null && link.predicted_class !== "hard_cut");
  const orderedRul = softRulLinks.map((link) => link.predicted_ttf_days).sort((a, b) => a - b);
  const middle = Math.floor(orderedRul.length / 2);
  const medianRul = !orderedRul.length ? null : orderedRul.length % 2
    ? orderedRul[middle]
    : (orderedRul[middle - 1] + orderedRul[middle]) / 2;
  const visibleStatusCounts = lifecycle === "ongoing"
    ? counts
    : { alert: counts.resolvedAlert, watch: counts.resolvedWatch, normal: counts.resolvedNormal };

  return (
    <div className="main">
      <div className="content monitoring-content">
        <div className="page-intro">
          <div>
            <div className="eyebrow">NETWORK OPERATIONS CENTER</div>
            <h1>Network overview</h1>
            <p>Understand link health, identify emerging failures, and prioritise maintenance.</p>
          </div>
          <div className="data-mode"><span className="live-dot" /> SIMULATED COHORT <span className="mode-divider">/</span> MODEL OUTPUTS</div>
        </div>

        <div className="overview-metrics-grid">
          <MetricCard label="Links monitored" value={links.length} note={`${counts.ongoing} active · ${counts.resolved_incident} resolved`} icon="◎" />
          <MetricCard label="Critical links" value={counts.alert} note="Require priority inspection" tone="alert" icon="!" />
          <MetricCard label="Watchlist" value={counts.watch} note="Degradation or elevated hazard" tone="watch" icon="◷" />
          <MetricCard label="Median estimated RUL" value={medianRul == null ? "—" : `${Math.round(medianRul)}d`} note={`${softRulLinks.length} active soft-failure estimates`} tone="accent" icon="⌁" />
        </div>

        <div className="overview-panels">
          <RiskDistribution counts={counts} total={activeLinks.length} />
          <RemainingLifeSummary links={links} />
        </div>

        <NetworkMap links={links} selected={selected} onSelect={setSelected} />

        <div className="reliability-strip">
          <div className="reliability-icon">↗</div>
          <div className="reliability-copy">
            <strong>Observed cohort failure rate</strong>
            <span>Historical events per 1,000 monitored link-days · simulated data only</span>
          </div>
          <div className="reliability-value mono">{analytics?.failures_per_1000_link_days ?? "—"}<small> / 1k link-days</small></div>
          <div className="reliability-count">{analytics?.observed_failures ?? 0} events <span>({analytics?.hard_failures ?? 0} hard · {analytics?.soft_failures ?? 0} soft)</span></div>
        </div>

        <div className="section-head link-section-head">
          <div>
            <div className="section-title">Fiber link explorer</div>
            <div className="section-hint">{filtered.length} links shown · sorted by urgency</div>
          </div>
          <div className="lifecycle-toggle">
            <button className={lifecycle === "ongoing" ? "active" : ""} onClick={() => setLifecycle("ongoing")}>
              Active ({counts.ongoing})
            </button>
            <button className={lifecycle === "resolved_incident" ? "active" : ""} onClick={() => setLifecycle("resolved_incident")}>
              Resolved ({counts.resolved_incident})
            </button>
          </div>
        </div>

        <div className="link-toolbar">
          <div className="status-filters" aria-label="Filter links by status">
            {FILTERS.map((filter) => (
              <button key={filter.id} className={statusFilter === filter.id ? "active" : ""} onClick={() => setStatusFilter(filter.id)}>
                {filter.label}{filter.id !== "all" && <span>{visibleStatusCounts[filter.id]}</span>}
              </button>
            ))}
          </div>
          <label className="link-search">
            <span aria-hidden="true">⌕</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search link or route" />
          </label>
        </div>

        <div className="link-grid">
          {filtered.map((link) => (
            <LinkCard key={link.link_id} link={link} selected={selected === link.link_id}
              onClick={() => setSelected(link.link_id)} />
          ))}
          {!filtered.length && <div className="empty-results">No links match these filters. Try another status or search term.</div>}
        </div>
        <div className="data-explainer">
          <strong>How to read these results</strong>
          <span><b>Remaining life</b> is Track B’s estimated time to a soft-failure condition. <b>Hazard percentile</b> is a relative rank against this cohort, not a probability of failure. The observed failure rate is a retrospective simulation statistic.</span>
        </div>
      </div>
      <div className="detail-panel">
        <DetailPanel linkId={selected} rulMaeDays={modelInfo?.track_b_ttf_regressor?.mae_days_soft_only} />
      </div>
    </div>
  );
}
