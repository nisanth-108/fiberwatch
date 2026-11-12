import { ResponsiveContainer, LineChart, Line, ReferenceLine } from "recharts";

const COLORS = { normal: "#3ddc97", watch: "#f5a623", alert: "#ff5d5d" };

export default function Sparkline({ trace, status }) {
  const data = trace;
  return (
    <div className="sparkline">
      <ResponsiveContainer width="100%" height={30}>
        <LineChart data={data}>
          <ReferenceLine y={18} stroke="#4e5868" strokeDasharray="2 2" />
          <Line type="monotone" dataKey="osnr" stroke={COLORS[status]} strokeWidth={1.4}
            dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
