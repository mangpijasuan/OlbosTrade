/**
 * SignalsCenter — single "Signals" nav entry combining the live Equity Signals
 * feed with the Strategy reference page (its "current signals" overlapped Equity
 * Signals). Tabs switch between the live feed and the strategy reference.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import EquitySignals from "./EquitySignals";
import Strategy from "./Strategy";

const TABS = [
  { key: "signals", label: "Live Signals" },
  { key: "strategies", label: "Strategies" },
];

export default function SignalsCenter() {
  const [tab, setTab] = useState("signals");
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      {tab === "signals" ? <EquitySignals /> : <Strategy />}
    </div>
  );
}
