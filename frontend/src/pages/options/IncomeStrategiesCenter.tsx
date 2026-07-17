import React, { useState } from "react";
import TabBar from "../../components/TabBar";
import CspScreener from "../CspScreener";
import IncomeMatrix from "../IncomeMatrix";

const TABS = [
  { key: "csp", label: "Cash-Secured Puts" },
  { key: "covered", label: "Covered Calls" },
  { key: "matrix", label: "Income Matrix" },
];

export default function IncomeStrategiesCenter({ initialTab = "csp" }: { initialTab?: string }) {
  const [tab, setTab] = useState(initialTab);
  return <div>
    <TabBar tabs={TABS} active={tab} onChange={setTab} label="Income strategy views" />
    {tab === "csp" ? <CspScreener /> : <IncomeMatrix initialFilter={tab === "covered" ? "cc" : undefined} />}
  </div>;
}
