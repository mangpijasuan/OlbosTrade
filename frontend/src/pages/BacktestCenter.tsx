/**
 * BacktestCenter — single "Backtest" nav entry. All three tabs are backtesters:
 *  - Backtest: the options-strategy backtester (date range + strategy + mode).
 *  - Symphony: the Composer-style no-code multi-asset strategy backtester.
 *  - Strategy Comparison: our equity signal engine vs. simple rule-based
 *    baselines (Buy & Hold, SMA, RSI, MACD) over the same window.
 * Symphony previously sat as its own nav entry, but it is just another form of
 * backtesting, so it now lives here behind a tab. Components reused as-is.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import ErrorBoundary from "../components/ErrorBoundary";
import Backtest from "./Backtest";
import Symphony from "./Symphony";
import StrategyComparison from "./StrategyComparison";

const TABS = [
  { key: "backtest", label: "Backtest" },
  { key: "symphony", label: "Symphony" },
  { key: "compare", label: "Strategy Comparison" },
];

export default function BacktestCenter() {
  const [tab, setTab] = useState("backtest");
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      <ErrorBoundary label={TABS.find((t) => t.key === tab)?.label || "Backtest"}>
        {tab === "backtest" ? <Backtest /> : tab === "symphony" ? <Symphony /> : <StrategyComparison />}
      </ErrorBoundary>
    </div>
  );
}
