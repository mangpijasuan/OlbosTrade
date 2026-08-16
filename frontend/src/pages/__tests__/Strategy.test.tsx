import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Strategy from "../Strategy";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { getStrategyRegistry: vi.fn() },
}));

const mockedApi = api as unknown as { getStrategyRegistry: ReturnType<typeof vi.fn> };

function card(overrides: object) {
  return {
    strategy_id: "bull_put_spread", name: "Bull Put Spread", lifecycle_status: "paper",
    enabled: true, manual_eligible: true, copilot_eligible: true, autopilot_supported: false,
    allocation_limit_pct: null, main_risk_warning: null,
    health_score: null, health_status: null, sample_size: 0,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Strategy (Strategy Cards)", () => {
  it("shows a loading state before the fetch resolves", () => {
    mockedApi.getStrategyRegistry.mockReturnValue(new Promise(() => {}));
    render(<Strategy />);
    expect(screen.getByText(/loading strategies/i)).toBeInTheDocument();
  });

  it("shows an explicit error state on fetch failure, not an empty list", async () => {
    mockedApi.getStrategyRegistry.mockRejectedValue(new Error("API error 500: Internal Server Error"));
    render(<Strategy />);
    await waitFor(() => expect(screen.getByText(/API error 500/)).toBeInTheDocument());
  });

  it("renders real strategies from the registry, not a hardcoded list", async () => {
    mockedApi.getStrategyRegistry.mockResolvedValue({
      strategies: [card({ strategy_id: "bull_put_spread", name: "Bull Put Spread" })],
      total: 1,
    });
    render(<Strategy />);
    await waitFor(() => expect(screen.getAllByText("Bull Put Spread").length).toBeGreaterThan(0));
  });

  it("shows insufficient-data state instead of a fabricated health score", async () => {
    mockedApi.getStrategyRegistry.mockResolvedValue({
      strategies: [card({ strategy_id: "bull_put_spread", name: "Bull Put Spread", health_status: "insufficient_data" })],
      total: 1,
    });
    render(<Strategy />);
    await waitFor(() => expect(screen.getByText(/insufficient closed-trade history/i)).toBeInTheDocument());
  });

  it("renders a live health score and status when present", async () => {
    mockedApi.getStrategyRegistry.mockResolvedValue({
      strategies: [card({
        strategy_id: "bull_put_spread", name: "Bull Put Spread",
        health_status: "healthy", health_score: 82.4, sample_size: 30,
      })],
      total: 1,
    });
    render(<Strategy />);
    await waitFor(() => expect(screen.getByText("82.4")).toBeInTheDocument());
    expect(screen.getByText("HEALTHY")).toBeInTheDocument();
    expect(screen.getByText("30 trades")).toBeInTheDocument();
  });

  it("renders eligibility flags and a risk warning when present", async () => {
    mockedApi.getStrategyRegistry.mockResolvedValue({
      strategies: [card({
        strategy_id: "iron_condor", name: "Iron Condor",
        autopilot_supported: false,
        main_risk_warning: "Suspended in capital-preservation mode.",
      })],
      total: 1,
    });
    render(<Strategy />);
    await waitFor(() => expect(screen.getByText(/suspended in capital-preservation mode/i)).toBeInTheDocument());
    expect(screen.getByText(/✕ Autopilot/)).toBeInTheDocument();
  });

  it("does not show a risk warning block when none is present", async () => {
    mockedApi.getStrategyRegistry.mockResolvedValue({
      strategies: [card({ strategy_id: "bull_put_spread", name: "Bull Put Spread", main_risk_warning: null })],
      total: 1,
    });
    render(<Strategy />);
    await waitFor(() => expect(screen.getAllByText("Bull Put Spread").length).toBeGreaterThan(0));
    expect(screen.queryByText(/suspended/i)).not.toBeInTheDocument();
  });
});
