import React from "react";

/**
 * Small hand-rolled SVG chart: a price line with buy/sell trade markers,
 * plus a thin equity-curve panel above it. Hand-rolled to match every other
 * chart in the app (ChartWorkstation's ChartCanvas is also hand-rolled SVG
 * despite the name) -- recharts is an installed-but-unused dependency, so
 * pulling it in just for this one chart would be inconsistent.
 */

interface Bar { date: string; close: number; }
interface Marker { date: string; action: "BUY" | "SELL"; price: number; }
interface EquityPoint { date: string; value: number; }

function pathFromPoints(points: Array<{ x: number; y: number }>) {
  if (!points.length) return "";
  return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");
}

export default function TradeMarkerChart({
  bars, markers, equityCurve, cursor,
}: { bars: Bar[]; markers: Marker[]; equityCurve: EquityPoint[]; cursor?: { date: string } }) {
  if (!bars.length) {
    return (
      <div style={{
        height: 300, display: "flex", alignItems: "center", justifyContent: "center",
        color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11,
      }}>
        NO CHART DATA
      </div>
    );
  }

  const width = 960;
  const equityHeight = 90;
  const priceHeight = 260;
  const pad = { top: 14, right: 60, bottom: 24, left: 14 };
  const contentWidth = width - pad.left - pad.right;

  const dateIndex = new Map(bars.map((b, i) => [b.date, i]));
  const xForIndex = (idx: number) => pad.left + (contentWidth * idx) / Math.max(bars.length - 1, 1);
  const cursorIdx = cursor ? dateIndex.get(cursor.date) : undefined;
  const cursorX = cursorIdx !== undefined ? xForIndex(cursorIdx) : undefined;

  // ── Price panel ────────────────────────────────────────────────────────
  const closes = bars.map((b) => b.close);
  const minPrice = Math.min(...closes) * 0.99;
  const maxPrice = Math.max(...closes) * 1.01;
  const priceRange = Math.max(maxPrice - minPrice, 0.01);
  const yForPrice = (price: number) => pad.top + ((maxPrice - price) / priceRange) * (priceHeight - pad.top);
  const pricePath = pathFromPoints(bars.map((b, i) => ({ x: xForIndex(i), y: yForPrice(b.close) })));

  // ── Equity panel ───────────────────────────────────────────────────────
  const values = equityCurve.map((e) => e.value);
  const minEquity = values.length ? Math.min(...values) * 0.995 : 0;
  const maxEquity = values.length ? Math.max(...values) * 1.005 : 1;
  const equityRange = Math.max(maxEquity - minEquity, 0.01);
  const yForEquity = (v: number) => (equityHeight - (v - minEquity) / equityRange * (equityHeight - 8)) - 4;
  const equityPath = pathFromPoints(equityCurve.map((e, i) => ({ x: xForIndex(i), y: yForEquity(e.value) })));

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${equityHeight}`} style={{ width: "100%", height: equityHeight, display: "block" }}>
        {equityPath && <path d={equityPath} fill="none" stroke="var(--cyan)" strokeWidth="1.6" />}
        {cursorX !== undefined && <line x1={cursorX} y1={0} x2={cursorX} y2={equityHeight} stroke="var(--amber)" strokeWidth="1" strokeDasharray="3 3" />}
        <text x={pad.left} y={12} fill="var(--ink-faint)" fontFamily="var(--mono)" fontSize="9">EQUITY</text>
      </svg>
      <svg viewBox={`0 0 ${width} ${priceHeight}`} style={{ width: "100%", height: priceHeight, display: "block" }}>
        {Array.from({ length: 4 }).map((_, idx) => {
          const y = pad.top + ((priceHeight - pad.top) * idx) / 3;
          const price = maxPrice - (priceRange * idx) / 3;
          return (
            <g key={idx}>
              <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 6" />
              <text x={width - pad.right + 8} y={y + 4} fill="rgba(148,163,184,0.8)" fontFamily="var(--mono)" fontSize="10">
                {price.toFixed(2)}
              </text>
            </g>
          );
        })}

        {pricePath && <path d={pricePath} fill="none" stroke="var(--ink)" strokeWidth="1.4" />}

        {markers.map((m, i) => {
          const idx = dateIndex.get(m.date);
          if (idx === undefined) return null;
          const x = xForIndex(idx);
          const y = yForPrice(m.price);
          const up = m.action === "BUY";
          const color = up ? "#18c37e" : "#ff5f6d";
          const size = 6;
          const trianglePoints = up
            ? `${x},${y + 10} ${x - size},${y + 10 + size} ${x + size},${y + 10 + size}`
            : `${x},${y - 10} ${x - size},${y - 10 - size} ${x + size},${y - 10 - size}`;
          return <polygon key={`${m.date}-${m.action}-${i}`} points={trianglePoints} fill={color} />;
        })}

        {cursorX !== undefined && (
          <line x1={cursorX} y1={pad.top} x2={cursorX} y2={priceHeight} stroke="var(--amber)" strokeWidth="1" strokeDasharray="3 3" />
        )}
      </svg>
    </div>
  );
}
