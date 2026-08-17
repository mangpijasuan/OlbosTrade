import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import SectorRotation from "../SectorRotation";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({
  api: { getSectorRotation: vi.fn() },
}));

const mockedApi = api as unknown as { getSectorRotation: ReturnType<typeof vi.fn> };

function response(overrides: object) {
  return {
    as_of: "2026-08-17T00:00:00+00:00",
    rank_basis: "1M",
    sectors: [
      {
        ticker: "XLK", name: "Technology",
        returns: { "1D": 0.012, "1W": 0.034, "1M": 0.081, "3M": 0.15 },
        rank: 1, prior_rank: 3, rank_change: 2,
      },
      {
        ticker: "XLU", name: "Utilities",
        returns: { "1D": -0.005, "1W": -0.01, "1M": -0.02, "3M": 0.01 },
        rank: 2, prior_rank: 1, rank_change: -1,
      },
    ],
    excluded: [],
    data_source: "yfinance daily bars",
    error: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SectorRotation", () => {
  it("renders ranked sector rows with returns", async () => {
    mockedApi.getSectorRotation.mockResolvedValue(response({}));
    render(<SectorRotation />);
    expect(await screen.findByText("XLK")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("+8.10%")).toBeInTheDocument();
    expect(screen.getByText("-2.00%")).toBeInTheDocument();
  });

  it("renders rank-change arrows for up and down movement", async () => {
    mockedApi.getSectorRotation.mockResolvedValue(response({}));
    render(<SectorRotation />);
    await waitFor(() => expect(screen.getByText("XLK")).toBeInTheDocument());
    expect(screen.getByText(/▲ 2/)).toBeInTheDocument();
    expect(screen.getByText(/▼ 1/)).toBeInTheDocument();
  });

  it("shows a dash for rank change when unavailable, not a fabricated arrow", async () => {
    mockedApi.getSectorRotation.mockResolvedValue(response({
      sectors: [{
        ticker: "XLE", name: "Energy",
        returns: { "1D": null, "1W": null, "1M": null, "3M": null },
        rank: null, prior_rank: null, rank_change: null,
      }],
    }));
    render(<SectorRotation />);
    expect(await screen.findByText("XLE")).toBeInTheDocument();
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("shows an explicit error state on fetch rejection", async () => {
    mockedApi.getSectorRotation.mockRejectedValue(new Error("network error"));
    render(<SectorRotation />);
    await waitFor(() => expect(screen.getByText(/Failed to load sector rotation/i)).toBeInTheDocument());
  });

  it("shows an in-band error field without inventing sector rows", async () => {
    mockedApi.getSectorRotation.mockResolvedValue(response({ sectors: [], error: "yfinance unreachable" }));
    render(<SectorRotation />);
    await waitFor(() => expect(screen.getByText(/yfinance unreachable/i)).toBeInTheDocument());
  });

  it("renders an amber note listing excluded sectors", async () => {
    mockedApi.getSectorRotation.mockResolvedValue(response({
      excluded: [{ ticker: "XLRE", name: "Real Estate", reason: "no data returned" }],
    }));
    render(<SectorRotation />);
    expect(await screen.findByText(/XLRE.*excluded.*no data returned/)).toBeInTheDocument();
  });
});
