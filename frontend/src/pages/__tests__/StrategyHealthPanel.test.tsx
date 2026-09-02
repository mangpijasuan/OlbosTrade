import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import StrategyHealthPanel from "../StrategyHealthPanel";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { getStrategyHealth: vi.fn() },
}));

const mockedApi = api as unknown as { getStrategyHealth: ReturnType<typeof vi.fn> };

function row(overrides: object) {
  return {
    strategy: "bull_put_spread", status: "healthy", action: "none",
    score: 82.4, volatility: 0.12, sample_size: 30, win_rate: 0.8,
    expectancy: 55.0, profit_factor: 2.1, drawdown_pct: 3.5, losing_streak: 1,
    expectancy_ratio: 1.1, reasons: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StrategyHealthPanel", () => {
  it("shows a loading state before the fetch resolves", () => {
    mockedApi.getStrategyHealth.mockReturnValue(new Promise(() => {}));
    render(<StrategyHealthPanel />);
    expect(screen.getByText(/loading strategy health/i)).toBeInTheDocument();
  });

  it("shows an explicit error state on fetch rejection", async () => {
    mockedApi.getStrategyHealth.mockRejectedValue(new Error("API error 500: Internal Server Error"));
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText(/API error 500/)).toBeInTheDocument());
  });

  it("shows an explicit error state for an in-band error field (HTTP 200 with error)", async () => {
    mockedApi.getStrategyHealth.mockResolvedValue({ strategies: [], error: "db down" });
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText("db down")).toBeInTheDocument());
  });

  it("shows an explicit empty state when no strategies are tracked yet", async () => {
    mockedApi.getStrategyHealth.mockResolvedValue({ strategies: [], suspended: [], total_strategies: 0 });
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText(/no strategies tracked yet/i)).toBeInTheDocument());
  });

  it("renders real strategy metrics", async () => {
    mockedApi.getStrategyHealth.mockResolvedValue({
      strategies: [row({ strategy: "iron_condor", status: "watch", score: 55 })],
      suspended: [], total_strategies: 1,
    });
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText("iron condor")).toBeInTheDocument());
    expect(screen.getByText("55")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("2.10")).toBeInTheDocument();
  });

  it("never drops the reasons list — the actual point of this slice", async () => {
    mockedApi.getStrategyHealth.mockResolvedValue({
      strategies: [row({
        strategy: "bull_call_debit_spread", status: "degraded", action: "suspend",
        reasons: ["negative live expectancy (-30.00)", "losing streak 7 exceeds baseline"],
      })],
      suspended: ["bull_call_debit_spread"], total_strategies: 1,
    });
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText("negative live expectancy (-30.00)")).toBeInTheDocument());
    expect(screen.getByText("losing streak 7 exceeds baseline")).toBeInTheDocument();
  });

  it("surfaces a prominent action badge when action is not none", async () => {
    mockedApi.getStrategyHealth.mockResolvedValue({
      strategies: [row({ strategy: "bear_call_spread", status: "degraded", action: "suspend" })],
      suspended: ["bear_call_spread"], total_strategies: 1,
    });
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText(/ACTION: SUSPEND NEW ENTRIES/)).toBeInTheDocument());
  });

  it("suppresses the action badge entirely when action is none", async () => {
    mockedApi.getStrategyHealth.mockResolvedValue({
      strategies: [row({ strategy: "bull_put_spread", status: "healthy", action: "none" })],
      suspended: [], total_strategies: 1,
    });
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText("bull put spread")).toBeInTheDocument());
    expect(screen.queryByText(/^ACTION:/)).not.toBeInTheDocument();
  });

  it("shows the suspended-strategy count and names in the summary bar", async () => {
    mockedApi.getStrategyHealth.mockResolvedValue({
      strategies: [row({ strategy: "iron_condor", status: "degraded", action: "suspend" })],
      suspended: ["iron_condor"], total_strategies: 4,
    });
    render(<StrategyHealthPanel />);
    await waitFor(() => expect(screen.getByText(/4 tracked/)).toBeInTheDocument());
    expect(screen.getByText(/1 suspended \(iron_condor\)/)).toBeInTheDocument();
  });
});
