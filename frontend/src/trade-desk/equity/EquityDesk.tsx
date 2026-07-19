/**
 * Equity Desk — discovery | chart | intelligence + order composer.
 * Phase C: display + evaluate + queue submit. No _execute_signal changes.
 */

import React, { useState } from "react";
import ChartWorkstation from "../../pages/ChartWorkstation";
import { PanelChrome, usePanelLayout } from "../PanelLayoutManager";
import EquityDiscoveryRail from "./EquityDiscoveryRail";
import EquityIntelligenceRail, { type EligibilitySnapshot } from "./EquityIntelligenceRail";
import EquityOrderComposer from "./EquityOrderComposer";

export default function EquityDesk() {
  const [symbol, setSymbol] = useState("AAPL");
  const [eligibility, setEligibility] = useState<EligibilitySnapshot | null>(null);
  const { layout, toggle, reset } = usePanelLayout();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        background: "var(--bg)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "6px 10px",
          borderBottom: "1px solid var(--line-dim)",
          flexShrink: 0,
          background: "var(--bg-2)",
        }}
      >
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            letterSpacing: "0.1em",
            color: "var(--ink-dim)",
          }}
        >
          EQUITY DESK
        </span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 14, fontWeight: 700, color: "var(--cyan)" }}>
          {symbol}
        </span>
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
          gap: 0,
        }}
      >
        <PanelChrome
          title="Discovery"
          collapsed={layout.discoveryCollapsed}
          onToggle={() => toggle("discovery")}
          style={{ minHeight: 0 }}
        >
          <EquityDiscoveryRail symbol={symbol} onSelect={setSymbol} />
        </PanelChrome>

        <div style={{ display: "flex", flexDirection: "column", minHeight: 0, borderLeft: "1px solid var(--line-dim)", borderRight: "1px solid var(--line-dim)" }}>
          <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
            <ChartWorkstation symbol={symbol} onSymbolChange={setSymbol} compact />
          </div>
          {!layout.activityCollapsed && (
            <EquityOrderComposer symbol={symbol} onEvaluated={setEligibility} />
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
            {layout.activityCollapsed ? "SHOW COMPOSER" : "HIDE COMPOSER"}
          </button>
        </div>

        <PanelChrome
          title="Intelligence"
          collapsed={layout.intelligenceCollapsed}
          onToggle={() => toggle("intelligence")}
          style={{ minHeight: 0 }}
        >
          <EquityIntelligenceRail symbol={symbol} eligibility={eligibility} />
        </PanelChrome>
      </div>
    </div>
  );
}
