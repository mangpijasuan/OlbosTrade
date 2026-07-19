/**
 * Options Desk — discovery | tool workspace | intelligence.
 * Phase D: assembly only. No Autopilot for 0DTE. No _execute_signal changes.
 */

import React, { useState } from "react";
import OptionsChain from "../../pages/options/OptionsChain";
import OptionsScanPanel from "../../components/OptionsScanPanel";
import IncomeStrategiesCenter from "../../pages/options/IncomeStrategiesCenter";
import OptionsFlow from "../../pages/OptionsFlow";
import OptionsSignals from "../../pages/OptionsSignals";
import ChartWorkstation from "../../pages/ChartWorkstation";
import { PanelChrome, usePanelLayout } from "../PanelLayoutManager";
import OptionsDiscoveryRail from "./OptionsDiscoveryRail";
import OptionsIntelligenceRail, { type OptionsEligibility } from "./OptionsIntelligenceRail";
import OptionsOrderComposer from "./OptionsOrderComposer";
import ZeroDteDesk from "./ZeroDteDesk";

type ToolTab = "chain" | "chart" | "scanner" | "income" | "flow" | "signals" | "zerodte";

const TOOLS: { key: ToolTab; label: string }[] = [
  { key: "chain", label: "Chain" },
  { key: "chart", label: "Chart" },
  { key: "scanner", label: "Scanner" },
  { key: "income", label: "Income" },
  { key: "flow", label: "Flow" },
  { key: "signals", label: "Signals" },
  { key: "zerodte", label: "0DTE" },
];

export default function OptionsDesk() {
  const [symbol, setSymbol] = useState("SPY");
  const [tool, setTool] = useState<ToolTab>("chain");
  const [eligibility, setEligibility] = useState<OptionsEligibility | null>(null);
  const { layout, toggle, reset } = usePanelLayout();

  let center: React.ReactNode;
  switch (tool) {
    case "chain":
      center = <OptionsChain symbol={symbol} onSymbolChange={setSymbol} />;
      break;
    case "chart":
      center = (
        <div style={{ padding: 8, height: "100%", overflow: "auto" }}>
          <ChartWorkstation symbol={symbol} onSymbolChange={setSymbol} compact />
        </div>
      );
      break;
    case "scanner":
      center = <OptionsScanPanel />;
      break;
    case "income":
      center = <IncomeStrategiesCenter />;
      break;
    case "flow":
      center = <OptionsFlow />;
      break;
    case "signals":
      center = <OptionsSignals />;
      break;
    case "zerodte":
      center = <ZeroDteDesk symbol={symbol} />;
      break;
    default:
      center = null;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, background: "var(--bg)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "6px 10px",
          borderBottom: "1px solid var(--line-dim)",
          flexShrink: 0,
          background: "var(--bg-2)",
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.1em", color: "var(--ink-dim)" }}>
          OPTIONS DESK
        </span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 14, fontWeight: 700, color: "var(--cyan)" }}>
          {symbol}
        </span>
        <div style={{ display: "flex", gap: 0, flexWrap: "wrap", marginLeft: 8 }}>
          {TOOLS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTool(t.key)}
              style={{
                padding: "6px 10px",
                border: "none",
                borderBottom: tool === t.key ? "2px solid var(--cyan)" : "2px solid transparent",
                background: "transparent",
                color: tool === t.key ? "var(--cyan)" : "var(--ink-dim)",
                fontFamily: "var(--mono)",
                fontSize: 10,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                cursor: "pointer",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button type="button" className="btn-t" style={{ fontSize: 10 }} onClick={reset}>
          Reset panels
        </button>
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: `${layout.discoveryCollapsed ? 36 : layout.discoveryWidth}px minmax(0, 1fr) ${
            layout.intelligenceCollapsed ? 36 : layout.intelligenceWidth
          }px`,
        }}
      >
        <PanelChrome
          title="Discovery"
          collapsed={layout.discoveryCollapsed}
          onToggle={() => toggle("discovery")}
          style={{ minHeight: 0 }}
        >
          <OptionsDiscoveryRail symbol={symbol} onSelect={setSymbol} />
        </PanelChrome>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            borderLeft: "1px solid var(--line-dim)",
            borderRight: "1px solid var(--line-dim)",
          }}
        >
          <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>{center}</div>
          {!layout.activityCollapsed && (
            <OptionsOrderComposer symbol={symbol} onEvaluated={setEligibility} />
          )}
          <button
            type="button"
            onClick={() => toggle("activity")}
            style={{
              border: "none",
              borderTop: "1px solid var(--line-dim)",
              background: "var(--bg-3)",
              color: "var(--ink-faint)",
              fontFamily: "var(--mono)",
              fontSize: 9,
              letterSpacing: "0.1em",
              padding: 4,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            {layout.activityCollapsed ? "SHOW GATE" : "HIDE GATE"}
          </button>
        </div>

        <PanelChrome
          title="Intelligence"
          collapsed={layout.intelligenceCollapsed}
          onToggle={() => toggle("intelligence")}
          style={{ minHeight: 0 }}
        >
          <OptionsIntelligenceRail symbol={symbol} eligibility={eligibility} />
        </PanelChrome>
      </div>
    </div>
  );
}
