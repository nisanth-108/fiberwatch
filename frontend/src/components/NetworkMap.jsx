const WAYPOINTS = [
  { name: "Guntur", lat: 16.3067, lon: 80.4365 },
  { name: "Vijayawada", lat: 16.5062, lon: 80.648 },
  { name: "Eluru", lat: 17.0005, lon: 81.7799 },
  { name: "Visakhapatnam", lat: 17.6868, lon: 83.2185 },
];

function project(lat, lon) {
  return {
    x: 42 + ((lon - 80.28) / (83.35 - 80.28)) * 620,
    y: 255 - ((lat - 16.22) / (17.78 - 16.22)) * 205,
  };
}

const ROUTE_POINTS = WAYPOINTS.map((point) => project(point.lat, point.lon));
const ROUTE_PATH = ROUTE_POINTS.map((point, index) => `${index ? "L" : "M"}${point.x},${point.y}`).join(" ");

export default function NetworkMap({ links, selected, onSelect }) {
  const activeLinks = links.filter((link) => link.lifecycle === "ongoing");
  return (
    <section className="overview-panel network-map-panel">
      <div className="panel-heading-row">
        <div>
          <div className="panel-heading">Fiber corridor map</div>
          <div className="panel-subheading">Select a point to inspect its link · approximate locations from the simulation route generator</div>
        </div>
        <div className="map-legend">
          <span><i className="normal" />Normal</span>
          <span><i className="watch" />Watch</span>
          <span><i className="alert" />Critical</span>
        </div>
      </div>
      <div className="map-canvas">
        <svg viewBox="0 0 700 300" role="img" aria-label="Simulated fiber route corridor from Guntur through Vijayawada and Eluru to Visakhapatnam">
          <defs>
            <linearGradient id="corridorGlow" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#4dd8c4" stopOpacity=".06" />
              <stop offset="1" stopColor="#4dd8c4" stopOpacity=".18" />
            </linearGradient>
          </defs>
          {[65, 125, 185, 245].map((y) => <line key={`h-${y}`} x1="20" y1={y} x2="680" y2={y} className="map-grid-line" />)}
          {[100, 220, 340, 460, 580].map((x) => <line key={`v-${x}`} x1={x} y1="20" x2={x} y2="270" className="map-grid-line" />)}
          <path d={ROUTE_PATH} fill="none" stroke="url(#corridorGlow)" strokeWidth="22" strokeLinecap="round" strokeLinejoin="round" />
          <path d={ROUTE_PATH} fill="none" stroke="#4dd8c4" strokeOpacity=".42" strokeWidth="2" strokeDasharray="5 7" strokeLinecap="round" />
          {WAYPOINTS.map((point, index) => {
            const pos = ROUTE_POINTS[index];
            const labelOffset = index === 0 ? { x: -4, y: 22 } : index === 3 ? { x: -8, y: -14 } : { x: 8, y: -12 };
            return (
              <g key={point.name}>
                <circle cx={pos.x} cy={pos.y} r="5" className="map-waypoint" />
                <text x={pos.x + labelOffset.x} y={pos.y + labelOffset.y} className="map-city-label">{point.name}</text>
              </g>
            );
          })}
          {activeLinks.map((link) => {
            const pos = project(link.lat, link.lon);
            return (
              <g key={link.link_id} className="map-link-point" onClick={() => onSelect(link.link_id)} role="button" tabIndex="0"
                onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onSelect(link.link_id)}
                aria-label={`${link.link_id}, ${link.status}, select link`}>
                {selected === link.link_id && <circle cx={pos.x} cy={pos.y} r="10" className="map-point-halo" />}
                <circle cx={pos.x} cy={pos.y} r={selected === link.link_id ? 5.2 : 3.4} className={`map-point ${link.status}`} />
                <circle cx={pos.x} cy={pos.y} r="10" fill="transparent" />
              </g>
            );
          })}
        </svg>
      </div>
      <div className="map-footer"><span>{activeLinks.length} active simulated links plotted</span><span>Locations are illustrative, not GPS-verified infrastructure positions</span></div>
    </section>
  );
}
