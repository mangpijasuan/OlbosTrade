import React from "react";
import PlannedModule from "./PlannedModule";

export default function Calendar() {
  return (
    <PlannedModule
      title="Calendar"
      blurb="Forward-looking economic and earnings calendar — FOMC, CPI/PPI, jobs, and per-symbol earnings dates — aligned to the active regime so the desk can pre-emptively tighten risk into known volatility windows."
      needs="an events source (e.g. yfinance earnings dates + an econ calendar) surfaced at /api/market/calendar"
      columns={["Date", "Event", "Symbol", "Prior", "Consensus"]}
    />
  );
}
