/**
 * SignalsCenter — single "Signals" nav entry combining the live Equity Signals
 * feed with the Strategy reference page (its "current signals" overlapped Equity
 * Signals). Tabs switch between the live feed and the strategy reference.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import ErrorBoundary from "../components/ErrorBoundary";
import EquitySignals from "./EquitySignals";
import Strategy from "./Strategy";
import OptionsFlow from "./OptionsFlow";
import IncomeMatrix from "./IncomeMatrix";

const TABS = [
  { key: "signals", label: "Live Signals" },
  { key: "flow", label: "Options Flow" },
  { key: "income", label: "Income Matrix" },
  { key: "strategies", label: "Strategies" },
];

export default function SignalsCenter({ initialTab = "signals" }: { initialTab?: string }) {
  const [tab, setTab] = useState(initialTab);
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      <ErrorBoundary label="Signals">
        {tab === "signals" ? <EquitySignals />
          : tab === "flow" ? <OptionsFlow />
          : tab === "income" ? <IncomeMatrix />
          : <Strategy />}
      </ErrorBoundary>
    </div>
  );
}
