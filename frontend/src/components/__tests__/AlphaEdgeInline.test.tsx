import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import AlphaEdgeInline, { OpportunityScorePill } from "../AlphaEdgeInline";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { getAlphaEdge: vi.fn() },
}));

const mockedApi = api as unknown as { getAlphaEdge: ReturnType<typeof vi.fn> };

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AlphaEdgeInline", () => {
  it("does not fetch until the operator expands it", () => {
    render(<AlphaEdgeInline ticker="AAPL" assetType="equity" />);
    expect(mockedApi.getAlphaEdge).not.toHaveBeenCalled();
  });

  it("fetches and renders entry/risk/lifecycle on expand", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue({
      entry_score: 62, hold_score: 71, exit_score: 29, risk_score: 34,
      lifecycle_state: "confirmed", opportunity_score: 58,
    });
    render(<AlphaEdgeInline ticker="AAPL" assetType="equity" />);
    fireEvent.click(screen.getByRole("button", { name: /alpha edge/i }));
    expect(mockedApi.getAlphaEdge).toHaveBeenCalledWith("AAPL", "equity");
    await waitFor(() => expect(screen.getByText("62")).toBeInTheDocument());
    expect(screen.getByText("34")).toBeInTheDocument();
    expect(screen.getByText("CONFIRMED")).toBeInTheDocument();
  });

  it("does not refetch on a second expand of the same card", async () => {
    mockedApi.getAlphaEdge.mockResolvedValue({
      entry_score: 50, hold_score: null, exit_score: null, risk_score: 40,
      lifecycle_state: "new", opportunity_score: 45,
    });
    render(<AlphaEdgeInline ticker="SPY" assetType="options" />);
    const btn = screen.getByRole("button", { name: /alpha edge/i });
    fireEvent.click(btn);
    await waitFor(() => expect(mockedApi.getAlphaEdge).toHaveBeenCalledTimes(1));
    fireEvent.click(btn);  // collapse
    fireEvent.click(btn);  // expand again
    expect(mockedApi.getAlphaEdge).toHaveBeenCalledTimes(1);
  });

  it("shows an error message when the lookup fails", async () => {
    mockedApi.getAlphaEdge.mockRejectedValue(new Error("network down"));
    render(<AlphaEdgeInline ticker="AAPL" assetType="equity" />);
    fireEvent.click(screen.getByRole("button", { name: /alpha edge/i }));
    await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
  });
});

describe("OpportunityScorePill", () => {
  it("renders the numeric score", () => {
    render(<OpportunityScorePill value={82} />);
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText("OPPORTUNITY")).toBeInTheDocument();
  });
});
