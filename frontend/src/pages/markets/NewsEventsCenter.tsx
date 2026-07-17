import React, { useState } from "react";
import TabBar from "../../components/TabBar";
import NewsCatalysts from "./NewsCatalysts";
import Calendar from "./Calendar";

const TABS = [{ key: "news", label: "News & Catalysts" }, { key: "calendar", label: "Calendar" }];

export default function NewsEventsCenter() {
  const [tab, setTab] = useState("news");
  return <div>
    <TabBar tabs={TABS} active={tab} onChange={setTab} label="News and event views" />
    <div id={`workspace-panel-${tab}`} role="tabpanel">
      {tab === "news" ? <NewsCatalysts /> : <Calendar />}
    </div>
  </div>;
}
