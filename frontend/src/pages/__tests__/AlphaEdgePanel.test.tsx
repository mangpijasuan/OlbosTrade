import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import AlphaEdgePanel from "../AlphaEdgePanel";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: {
    getAlphaEdge: vi.fn(),
    getPositions: vi.fn(),
    getEquitySignals: vi.fn(),
    getOptionsSignals: vi.fn(),
  },
}));

const mockedApi = api as unknown as {
  getAlphaEdge: ReturnType<typeof vi.fn>;
  getPositions: ReturnType<typeof vi.fn>;
  getEquitySignals: ReturnType<typeof vi.fn>;
  getOptionsSignals: ReturnType<typeof vi.fn>;
};

function response(overrides: object) {
  return {
    ticker: "AAPL", asset_type: "equity",
    entry_score: 62, hold_score: 71, exit_score: 29,
    exit_score_basis: "inverse_of_hold_score", risk_score: 34,
    lifecycle_state: "confirmed",
    score_trend: { direction: "improving", delta: 9.0, basis: "vs signal recorded 2026-08-10" },
    current_action: "BUY", current_confidence: 0.71,
    position: { held: true, direction: "BUY", quantity: 40 },
    supporting_evidence: [{ feature: "macd_bull_cross", impact: 2.0 }],
    deterioration_evidence: [{ feature: "rsi_overbought", impact: -1.5 }],
    data_sources: { indicators: "yfinance daily bars", position: "broker" },
    error: null,
    opportunity_score: 78,
    ...overrides,
  };
}

function mockWatchlist() {
  mockedApi.getPositions.mockResolvedValue({
    positions: [{ symbol: "AAPL", asset_type: "equity", tracked: true }],
  });
  mockedApi.getEquitySignals.mockResolvedValue({
    signals: [{
      ticker: "AMD",
      action: "BUY",
      confidence: 0.82,
      generated_at: new Date().toISOString(),
    }],
  });
  mockedApi.getOptionsSignals.mockResolvedValue({ signals: [] });
}

async function lookup(symbol = "TSLA") {
  fireEvent.change(screen.getByLabelText(/alpha edge symbol lookup/i), { target: { value: symbol } });
  fireEvent.click(screen.getByRole("button", { name: /look up/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mockWatchlist();
  mockedApi.getAlphaEdge.mockImplementation((ticker: string) =>
    Promise.resolve(response({ ticker, entry_score: ticker === "AAPL" ? 62 : 88 })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AlphaEdgePanel", () => {
  it("auto-loads positions and scan candidates on mount", async () => {
    render(<AlphaEdgePanel />);
    await waitFor(() => expect(mockedApi.getPositions).toHaveBeenCalled());
    expect(await screen.findByText("OPEN POSITIONS (1)")).toBeInTheDocument();
    expect(screen.getByText("SCAN CANDIDATES (1)")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("AMD")).toBeInTheDocument();
    await waitFor(() => expect(mockedApi.getAlphaEdge).toHaveBeenCalledWith("AAPL", "equity"));
    await waitFor(() => expect(mockedApi.getAlphaEdge).toHaveBeenCalledWith("AMD", "equity"));
  });

  it("shows detail for the first auto-selected ticker", async () => {
    render(<AlphaEdgePanel />);
    expect(await screen.findByText("ENTRY SCORE")).toBeInTheDocument();
    const entryTiles = screen.getAllByText("62");
    expect(entryTiles.length).toBeGreaterThanOrEqual(1);
  });

  it("looks up a manual symbol and renders scores", async () => {
    mockedApi.getAlphaEdge.mockImplementation((ticker: string) =>
      Promise.resolve(response({
        ticker,
        hold_score: null,
        exit_score: null,
        lifecycle_state: ticker === "TSLA" ? "new" : "confirmed",
        position: { held: ticker !== "TSLA" },
      })),
    );
    render(<AlphaEdgePanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    await lookup("TSLA");
    await waitFor(() => expect(mockedApi.getAlphaEdge).toHaveBeenCalledWith("TSLA", "equity"));
    expect(await screen.findByText("NEW")).toBeInTheDocument();
  });

  it("shows an explicit error state on fetch rejection for manual lookup", async () => {
    mockedApi.getAlphaEdge.mockImplementation((ticker: string) => {
      if (ticker === "BAD") return Promise.reject(new Error("API error 500"));
      return Promise.resolve(response({ ticker }));
    });
    render(<AlphaEdgePanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    await lookup("BAD");
    await waitFor(() => expect(screen.getByText(/API error 500/)).toBeInTheDocument());
  });

  it("switches asset type via AssetToggle and requests options scores", async () => {
    mockedApi.getPositions.mockResolvedValue({
      positions: [{ symbol: "SPY", asset_type: "options" }],
    });
    mockedApi.getOptionsSignals.mockResolvedValue({
      signals: [{
        ticker: "QQQ",
        action: "BUY_SPREAD",
        signal_score: 0.75,
        generated_at: new Date().toISOString(),
      }],
    });
    mockedApi.getAlphaEdge.mockResolvedValue(response({ ticker: "SPY", asset_type: "options" }));
    render(<AlphaEdgePanel />);
    fireEvent.click(screen.getByRole("button", { name: /options/i }));
    await waitFor(() => expect(mockedApi.getOptionsSignals).toHaveBeenCalled());
    await waitFor(() => expect(mockedApi.getAlphaEdge).toHaveBeenCalledWith("SPY", "options"));
  });
});
