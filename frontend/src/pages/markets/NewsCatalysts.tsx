import React from "react";
import PlannedModule from "./PlannedModule";

export default function NewsCatalysts() {
  return (
    <PlannedModule
      title="News & Catalysts"
      blurb="A filtered tape of headlines and scheduled catalysts for the watchlist — earnings, upgrades/downgrades, guidance, and macro prints — ranked by expected impact so you can size around events instead of getting surprised by them."
      needs="a news feed (e.g. yfinance news, Finnhub, or Benzinga) surfaced at /api/market/news"
      columns={["Time", "Symbol", "Headline", "Type", "Impact"]}
    />
  );
}
