import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, ReferenceLine, Tooltip } from "recharts";

function RealTrace({ trace }) {
  const data = trace.filter((d) => d.osnr != null);
  return (
    <ResponsiveContainer width="100%" height={170}>
      <AreaChart data={data} margin={{ top: 10, right: 10, bottom: 4, left: -6 }}>
        <defs>
          <linearGradient id="realFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#4dd8c4" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#4dd8c4" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="t" tick={{ fill: "#4e5868", fontSize: 9.5, fontFamily: "IBM Plex Mono" }}
          axisLine={{ stroke: "#232d3d" }} tickLine={false} tickFormatter={(v) => `${Math.round(v / 60)}m`} />
        <YAxis tick={{ fill: "#4e5868", fontSize: 9.5, fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} width={26} />
        <ReferenceLine y={18} stroke="#f5a623" strokeDasharray="3 3" strokeOpacity={0.6} />
        <Tooltip contentStyle={{ background: "#0d1219", border: "1px solid #232d3d", fontSize: 11, fontFamily: "IBM Plex Mono" }} />
        <Area type="monotone" dataKey="osnr" stroke="#4dd8c4" strokeWidth={1.4} fill="url(#realFill)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function DatasetCard({ title, d, note }) {
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className="card-subtitle">{d.n_samples.toLocaleString()} real telemetry samples &middot; {d.n_failure_samples.toLocaleString()} during emulated failure</div>
      <RealTrace trace={d.trace} />
      <div className="detail-grid" style={{ marginTop: 14 }}>
        <div className="detail-stat-box">
          <div className="detail-stat-label">OSNR, normal</div>
          <div className="detail-stat-value mono normal">{d.osnr_mean_normal} dB</div>
        </div>
        <div className="detail-stat-box">
          <div className="detail-stat-label">OSNR, during failure</div>
          <div className="detail-stat-value mono watch">{d.osnr_mean_during_failure} dB</div>
        </div>
        <div className="detail-stat-box" style={{ gridColumn: "1 / -1" }}>
          <div className="detail-stat-label">OSNR minimum observed during failure</div>
          <div className="detail-stat-value mono alert">{d.osnr_min_during_failure} dB</div>
        </div>
      </div>
      <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.6, marginTop: 12 }}>{note}</p>
    </div>
  );
}

export default function HardwareValidationView({ data }) {
  return (
    <div className="content">
      <div className="section-head">
        <div>
          <div className="section-title">Real hardware validation</div>
          <div className="section-hint">Independent check against actual optical-testbed telemetry &mdash; not simulated</div>
        </div>
      </div>

      <div className="callout" style={{ marginBottom: 16 }}>
        <b>Source.</b> {data.source}. Sampled every 3.5s from two Ericsson SPO 1400 devices
        over a 240km, 4-EDFA DWDM span. Bundled directly in this app; nothing here is fetched
        at runtime.
      </div>

      <div className="panel-grid">
        <DatasetCard title="Hard-failure emulation" d={data.hard}
          note="A 25dB attenuation event injected every 40 seconds. OSNR collapses toward 0dB near-instantly and recovers just as fast once the fault clears &mdash; the real-hardware signature of a step failure, with effectively no ramp to detect in advance." />
        <DatasetCard title="Soft-failure emulation" d={data.soft}
          note={`Variable attenuation in the 0\u201318dB range. The observed OSNR floor here (${data.soft.osnr_min_during_failure}dB) lands almost exactly on the 18dB soft-alarm threshold this app uses \u2014 drawn independently from ITU-T G.709 and the reference architecture, not fitted to this dataset.`} />
      </div>
    </div>
  );
}
