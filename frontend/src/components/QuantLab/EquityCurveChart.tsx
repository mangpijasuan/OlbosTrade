/**
 * EquityCurveChart — lightweight SVG-based equity and drawdown curves.
 * No external charting dependency — reuses the terminal design language.
 */

import React, { useMemo } from "react";

interface EquityPoint { date: string; equity: number; }
interface DrawdownPoint { date: string; drawdown_pct: number; }

interface Props {
  equityCurve:   EquityPoint[];
  drawdownCurve: DrawdownPoint[];
  height?:       number;
}

function Sparkline({
  data, minVal, maxVal, width = 600, height = 120,
  strokeColor = "var(--cyan)", fillColor = "rgba(0,200,200,0.08)",
}: {
  data: number[]; minVal: number; maxVal: number;
  width?: number; height?: number;
  strokeColor?: string; fillColor?: string;
}) {
  if (data.length < 2) return null;

  const pad = 4;
  const range = maxVal - minVal || 1;
  const xStep = (width - pad * 2) / (data.length - 1);

  const toY = (v: number) => pad + ((maxVal - v) / range) * (height - pad * 2);

  const points = data.map((v, i) => [pad + i * xStep, toY(v)] as [number, number]);
  const pathD  = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const fillD  = `${pathD} L${points[points.length - 1][0].toFixed(1)},${height} L${pad},${height} Z`;

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      <path d={fillD} fill={fillColor} />
      <path d={pathD} fill="none" stroke={strokeColor} strokeWidth="1.5" />
    </svg>
  );
}

export default function EquityCurveChart({ equityCurve, drawdownCurve, height = 120 }: Props) {
  const equityVals   = useMemo(() => equityCurve.map(p => p.equity), [equityCurve]);
  const drawdownVals = useMemo(() => drawdownCurve.map(p => p.drawdown_pct), [drawdownCurve]);

  if (equityVals.length < 2) {
    return (
      <div style={{ color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11, textAlign: "center", padding: 24 }}>
        No equity curve data available.
      </div>
    );
  }

  const eqMin = Math.min(...equityVals);
  const eqMax = Math.max(...equityVals);
  const ddMin = Math.min(...drawdownVals);
  const ddMax = Math.max(0, ...drawdownVals);

  const firstDate = equityCurve[0]?.date ?? "";
  const lastDate  = equityCurve[equityCurve.length - 1]?.date ?? "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Equity Curve */}
      <div>
        <div style={{
          display: "flex", justifyContent: "space-between",
          fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-dim)",
          marginBottom: 4, letterSpacing: "0.06em", textTransform: "uppercase",
        }}>
          <span>Equity Curve</span>
          <span>{firstDate} → {lastDate}</span>
        </div>
        <div style={{ background: "var(--bg-3)", border: "1px solid var(--line-dim)", padding: "6px 0" }}>
          <Sparkline
            data={equityVals} minVal={eqMin} maxVal={eqMax} height={height}
            strokeColor="var(--cyan)" fillColor="rgba(0,220,220,0.06)"
          />
          <div style={{
            display: "flex", justifyContent: "space-between", padding: "2px 8px",
            fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)",
          }}>
            <span>${eqMin.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
            <span>${eqMax.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
          </div>
        </div>
      </div>

      {/* Drawdown Curve */}
      {drawdownVals.length > 1 && (
        <div>
          <div style={{
            fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-dim)",
            marginBottom: 4, letterSpacing: "0.06em", textTransform: "uppercase",
          }}>
            Drawdown
          </div>
          <div style={{ background: "var(--bg-3)", border: "1px solid var(--line-dim)", padding: "6px 0" }}>
            <Sparkline
              data={drawdownVals} minVal={ddMin} maxVal={ddMax} height={Math.round(height * 0.6)}
              strokeColor="var(--red)" fillColor="rgba(220,50,50,0.08)"
            />
            <div style={{
              display: "flex", justifyContent: "space-between", padding: "2px 8px",
              fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)",
            }}>
              <span>{ddMin.toFixed(1)}%</span>
              <span>0%</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
