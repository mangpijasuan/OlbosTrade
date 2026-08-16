import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import OptionsSignalHistory from "../OptionsSignalHistory";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { getOptionsSignalHistory: vi.fn() },
}));

const mockedApi = api as unknown as { getOptionsSignalHistory: ReturnType<typeof vi.fn> };

function row(overrides: object) {
  return {
    id: "hist-1", ticker: "SPY", strategy: "bull_put_spread", action: "SELL_SPREAD",
    confidence: 0.82, pop: 0.78, kelly_fraction: 0.12, signal_score: 0.65,
    quantity: 2, iv_rank: 45.0, regime: "normal_mean_revert",
    spread: {
      option_type: "put", short_strike: 495, long_strike: 490,
      expiration: "2026-09-19", dte: 34, net_credit: 1.5, max_loss: 3.5, breakeven: 493.5,
    },
    sigma: 0.18, vix_used: 16.5, credit_source: "ibkr",
    evidence: null, intelligence: null,
    generated_at: "2026-08-16T14:30:00+00:00",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OptionsSignalHistory", () => {
  it("shows a loading state before the fetch resolves", () => {
    mockedApi.getOptionsSignalHistory.mockReturnValue(new Promise(() => {}));
    render(<OptionsSignalHistory />);
    expect(screen.getByText(/loading options signal history/i)).toBeInTheDocument();
  });

  it("shows an explicit error state on fetch failure", async () => {
    mockedApi.getOptionsSignalHistory.mockRejectedValue(new Error("API error 500: Internal Server Error"));
    render(<OptionsSignalHistory />);
    await waitFor(() => expect(screen.getByText(/API error 500/)).toBeInTheDocument());
  });

  it("renders persisted signals from the history endpoint", async () => {
    mockedApi.getOptionsSignalHistory.mockResolvedValue({ signals: [row({})], total: 1 });
    render(<OptionsSignalHistory />);
    await waitFor(() => expect(screen.getAllByText("SPY").length).toBeGreaterThan(0));
    expect(screen.getByText("bull put spread")).toBeInTheDocument();
    expect(screen.getByText("P 495/490")).toBeInTheDocument();
  });

  it("shows the not-an-outcome-study banner explaining the missing status column", async () => {
    mockedApi.getOptionsSignalHistory.mockResolvedValue({ signals: [row({})], total: 1 });
    render(<OptionsSignalHistory />);
    await waitFor(() => expect(screen.getByText(/not a win-rate study/i)).toBeInTheDocument());
  });

  it("never renders a status or hit-rate column — no outcome tracking exists for options yet", async () => {
    mockedApi.getOptionsSignalHistory.mockResolvedValue({ signals: [row({})], total: 1 });
    render(<OptionsSignalHistory />);
    await waitFor(() => expect(screen.getAllByText("SPY").length).toBeGreaterThan(0));
    expect(screen.queryByText(/hit rate/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^status$/i)).not.toBeInTheDocument();
  });

  it("shows an explicit empty state when nothing has been persisted yet", async () => {
    mockedApi.getOptionsSignalHistory.mockResolvedValue({ signals: [], total: 0 });
    render(<OptionsSignalHistory />);
    await waitFor(() => expect(screen.getByText(/no options signals persisted yet/i)).toBeInTheDocument());
  });
});
