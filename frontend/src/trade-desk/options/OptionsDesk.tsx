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
      <div className="desk-tool-rail" style={{ flexWrap: "wrap", alignItems: "center" }}>
        <span className="kicker" style={{ letterSpacing: "0.1em", textTransform: "uppercase" }}>
          Options desk
        </span>
        <span className="mono" style={{ fontSize: 14, fontWeight: 700, color: "var(--accent)" }}>
          {symbol}
        </span>
        <div style={{ display: "flex", gap: 2, marginLeft: 8, flexWrap: "wrap" }}>
          {TOOLS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTool(t.key)}
              className={`desk-tool-rail__btn${tool === t.key ? " desk-tool-rail__btn--active" : ""}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button type="button" className="btn-ghost" style={{ padding: "4px 10px", fontSize: 10 }} onClick={reset}>
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
            className="desk-tool-rail__btn"
            style={{
              width: "100%",
              borderRadius: 0,
              borderTop: "1px solid var(--line-dim)",
              padding: 6,
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
