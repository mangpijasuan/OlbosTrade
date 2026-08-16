/**
 * SignalsCenter — single "Signals" nav entry combining the live Equity Signals
 * feed with the Strategy reference page (its "current signals" overlapped Equity
 * Signals), plus a History tab surfacing each asset class's persisted signal log.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import ErrorBoundary from "../components/ErrorBoundary";
import EquitySignals, { AssetToggle, type AssetTab } from "./EquitySignals";
import Strategy from "./Strategy";
import SignalResearch from "./SignalResearch";
import OptionsSignalHistory from "./OptionsSignalHistory";

const TABS = [
  { key: "signals", label: "Live Signals" },
  { key: "history", label: "History" },
  { key: "strategies", label: "Strategy Library" },
];

function SignalsHistory() {
  const [asset, setAsset] = useState<AssetTab>("equities");
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "12px 16px 0" }}>
        <AssetToggle tab={asset} onChange={setAsset} />
      </div>
      <div style={{ flex: 1, overflow: asset === "equities" ? "hidden" : "auto", padding: asset === "options" ? 16 : 0 }}>
        {asset === "equities" ? <SignalResearch /> : <OptionsSignalHistory />}
      </div>
    </div>
  );
}

export default function SignalsCenter({ initialTab = "signals" }: { initialTab?: string }) {
  const [tab, setTab] = useState(initialTab);
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} label="Signal views" />
      <ErrorBoundary label="Signals">
        {tab === "signals" ? <EquitySignals /> : tab === "history" ? <SignalsHistory /> : <Strategy />}
      </ErrorBoundary>
    </div>
  );
}
