import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import AlphaEdgePanel from "../AlphaEdgePanel";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { getAlphaEdge: vi.fn() },
}));

const mockedApi = api as unknown as { getAlphaEdge: ReturnType<typeof vi.fn> };

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
    ...overrides,
  };
}

async function lookup(symbol = "AAPL") {
  fireEvent.change(screen.getByLabelText(/alpha edge symbol lookup/i), { target: { value: symbol } });
  fireEvent.click(screen.getByRole("button", { name: /look up/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AlphaEdgePanel", () => {
  it("shows an empty prompt before any lookup", () => {
    render(<AlphaEdgePanel />);
    expect(screen.getByText(/enter a symbol to look up/i)).toBeInTheDocument();
  });

  it("looks up a symbol and renders real scores", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue(response({}));
    render(<AlphaEdgePanel />);
    await lookup("AAPL");
    await waitFor(() => expect(mockedApi.getAlphaEdge).toHaveBeenCalledWith("AAPL", "equity"));
    expect(await screen.findByText("62")).toBeInTheDocument();
    expect(screen.getByText("71")).toBeInTheDocument();
    expect(screen.getByText("29")).toBeInTheDocument();
    expect(screen.getByText("34")).toBeInTheDocument();
  });

  it("shows a dash for hold/exit scores when no position exists, not a fabricated number", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue(response({
      hold_score: null, exit_score: null, lifecycle_state: "new",
      position: { held: false },
    }));
    render(<AlphaEdgePanel />);
    await lookup("TSLA");
    expect(await screen.findByText("NEW")).toBeInTheDocument();
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2); // hold + exit tiles
  });

  it("renders the lifecycle badge with the correct label", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue(response({ lifecycle_state: "decaying" }));
    render(<AlphaEdgePanel />);
    await lookup("AAPL");
    expect(await screen.findByText("DECAYING")).toBeInTheDocument();
  });

  it("shows an explicit error state on fetch rejection", async () => {
    mockedApi.getAlphaEdge.mockRejectedValue(new Error("API error 500: Internal Server Error"));
    render(<AlphaEdgePanel />);
    await lookup("AAPL");
    await waitFor(() => expect(screen.getByText(/API error 500/)).toBeInTheDocument());
  });

  it("shows an explicit error for an in-band error field (HTTP 200 with error)", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue(response({
      entry_score: null, error: "insufficient bar history for XYZ (5 bars)",
    }));
    render(<AlphaEdgePanel />);
    await lookup("XYZ");
    await waitFor(() => expect(screen.getByText(/insufficient bar history/i)).toBeInTheDocument());
  });

  it("passes evidence through to SignalAttribution without inventing a confidence value", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue(response({}));
    render(<AlphaEdgePanel />);
    await lookup("AAPL");
    expect(await screen.findByText(/macd bull cross/i)).toBeInTheDocument();
    expect(screen.getByText(/rsi overbought/i)).toBeInTheDocument();
  });

  it("switches asset type via AssetToggle and requests options scores", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue(response({ asset_type: "options" }));
    render(<AlphaEdgePanel />);
    fireEvent.click(screen.getByRole("button", { name: /options/i }));
    await lookup("SPY");
    await waitFor(() => expect(mockedApi.getAlphaEdge).toHaveBeenCalledWith("SPY", "options"));
  });
});
