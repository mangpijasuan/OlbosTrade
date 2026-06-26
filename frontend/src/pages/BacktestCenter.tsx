/**
 * BacktestCenter — single "Backtest" nav entry. Both tabs are backtesters:
 *  - Backtest: the options-strategy backtester (date range + strategy + mode).
 *  - Symphony: the Composer-style no-code multi-asset strategy backtester.
 * Symphony previously sat as its own nav entry, but it is just another form of
 * backtesting, so it now lives here behind a tab. Both components reused as-is.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import Backtest from "./Backtest";
import Symphony from "./Symphony";

const TABS = [
  { key: "backtest", label: "Backtest" },
  { key: "symphony", label: "Symphony" },
];

export default function BacktestCenter() {
  const [tab, setTab] = useState("backtest");
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      {tab === "backtest" ? <Backtest /> : <Symphony />}
    </div>
  );
}
