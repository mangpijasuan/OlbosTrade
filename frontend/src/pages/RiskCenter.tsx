/**
 * RiskCenter — single "Risk" nav entry combining the Risk Monitor and Guardrails
 * pages (both were built on the same useRisk hook). Tabs switch between them; the
 * underlying page components are reused unchanged.
 */
import React, { useState } from "react";
import TabBar from "../components/TabBar";
import RiskMonitor from "./RiskMonitor";
import Guardrails from "./Guardrails";

const TABS = [
  { key: "monitor", label: "Risk Monitor" },
  { key: "guardrails", label: "Guardrails" },
];

export default function RiskCenter({ initialTab = "monitor" }: { initialTab?: string }) {
  const [tab, setTab] = useState(initialTab);
  return (
    <div>
      <TabBar tabs={TABS} active={tab} onChange={setTab} />
      {tab === "monitor" ? <RiskMonitor /> : <Guardrails />}
    </div>
  );
}
