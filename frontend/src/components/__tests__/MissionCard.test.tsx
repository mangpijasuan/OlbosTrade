import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MissionCard from "../MissionCard";

describe("MissionCard", () => {
  it("renders reward, title, meta, and progress", () => {
    render(
      <MissionCard
        reward={{ prefix: "OPP", value: "72", tone: "var(--green)" }}
        title="AAPL"
        subtitle="BUY signal · Entry 62"
        meta={{ label: "CONFIRMED", icon: "⏳" }}
        progress={{ value: 62, tone: "var(--green)" }}
      />,
    );
    expect(screen.getByText("OPP")).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText(/BUY signal/)).toBeInTheDocument();
    expect(screen.getByText("CONFIRMED")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "62");
  });

  it("renders compact variant", () => {
    render(
      <MissionCard
        variant="compact"
        title="SPY"
        subtitle="$450.12"
        reward={{ value: "+0.42%", tone: "var(--green)" }}
      />,
    );
    expect(document.querySelector(".mission-card--compact")).toBeTruthy();
    expect(screen.getByText("SPY")).toBeInTheDocument();
  });
});
