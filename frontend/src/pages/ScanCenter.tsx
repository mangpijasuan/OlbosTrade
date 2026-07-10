/**
 * ScanCenter — single "Scanner" nav entry folding the EV-ranked scan engines:
 *   - Options Scan (options_scan_engine: EV ranking, Kelly ladders, NO-TRADE gates)
 *   - Equity Scan  (equity_scan_engine: EV ranking, entry ladders)
 *
 * Scans feed MANUAL / COPILOT execution. Autopilot auto-execution directly from
 * scans is intentionally disabled server-side (in trade_desk.submit_scan_signal)
 * until that path has test coverage.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import ErrorBoundary from "../components/ErrorBoundary";
import OptionsScan from "./OptionsScan";
import EquityScan from "./EquityScan";

const TABS = [
  { key: "options", label: "Options Scan" },
  { key: "equity", label: "Equity Scan" },
];

export default function ScanCenter() {
  const [tab, setTab] = useState("options");
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      <ErrorBoundary label="Scanner">
        {tab === "options" ? <OptionsScan /> : <EquityScan />}
      </ErrorBoundary>
    </div>
  );
}
