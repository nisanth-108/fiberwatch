import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, ReferenceLine, Tooltip } from "recharts";

const SOFT_ALARM = 18;
const HARD_FAIL = 15;

function TraceTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{
      background: "#0d1219", border: "1px solid #232d3d", borderRadius: 4,
      padding: "6px 10px", fontSize: 11, fontFamily: "IBM Plex Mono, monospace", color: "#e8edf2",
    }}>
      <div style={{ color: "#8b96a8", marginBottom: 3 }}>day {label}</div>
      <div>OSNR {p.osnr?.toFixed(2)} dB</div>
      {p.laser_current != null && <div>I_bias {p.laser_current?.toFixed(2)} mA</div>}
    </div>
  );
}

export default function SignalTrace({ data, height = 190, failureDay = null, showAxes = true }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 14, bottom: showAxes ? 4 : 0, left: showAxes ? -6 : 0 }}>
        <defs>
          <linearGradient id="traceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#4dd8c4" stopOpacity={0.28} />
            <stop offset="100%" stopColor="#4dd8c4" stopOpacity={0} />
          </linearGradient>
          <filter id="traceGlow" x="-20%" y="-50%" width="140%" height="220%">
            <feGaussianBlur stdDeviation="3.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {showAxes && (
          <XAxis dataKey="day" tick={{ fill: "#4e5868", fontSize: 10, fontFamily: "IBM Plex Mono" }}
            axisLine={{ stroke: "#232d3d" }} tickLine={false} />
        )}
        {showAxes && (
          <YAxis domain={[0, 25]} tick={{ fill: "#4e5868", fontSize: 10, fontFamily: "IBM Plex Mono" }}
            axisLine={false} tickLine={false} width={28} />
        )}
        <ReferenceLine y={SOFT_ALARM} stroke="#f5a623" strokeDasharray="3 3" strokeOpacity={0.6}
          label={showAxes ? { value: "soft alarm 18dB", position: "insideTopRight", fill: "#f5a623", fontSize: 9.5 } : undefined} />
        <ReferenceLine y={HARD_FAIL} stroke="#ff5d5d" strokeDasharray="3 3" strokeOpacity={0.6}
          label={showAxes ? { value: "hard-fail 15dB", position: "insideBottomRight", fill: "#ff5d5d", fontSize: 9.5 } : undefined} />
        {failureDay != null && (
          <ReferenceLine x={failureDay} stroke="#ff5d5d" strokeWidth={1.4} strokeOpacity={0.8} />
        )}
        {showAxes && <Tooltip content={<TraceTooltip />} />}
        <Area type="monotone" dataKey="osnr" stroke="#4dd8c4" strokeWidth={1.6}
          fill="url(#traceFill)" dot={false} isAnimationActive={false} filter="url(#traceGlow)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
