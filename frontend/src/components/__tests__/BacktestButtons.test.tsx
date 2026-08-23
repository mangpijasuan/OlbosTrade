import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import BacktestButtons from "../BacktestButtons";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: {
    runBacktest: vi.fn(),
    runEquityBacktest: vi.fn(),
    getBacktestResults: vi.fn(),
  },
}));

const nav = vi.fn();
vi.mock("../TerminalNavContext", () => ({
  useTerminalNav: () => nav,
}));

const mockedApi = api as unknown as {
  runBacktest: ReturnType<typeof vi.fn>;
  runEquityBacktest: ReturnType<typeof vi.fn>;
  getBacktestResults: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BacktestButtons", () => {
  it("REPLAY and HISTORY navigate via the terminal nav context", () => {
    render(<BacktestButtons ticker="AAPL" assetType="equity" />);
    fireEvent.click(screen.getByRole("button", { name: /replay/i }));
    expect(nav).toHaveBeenCalledWith("trade:replay");
    fireEvent.click(screen.getByRole("button", { name: /history/i }));
    expect(nav).toHaveBeenCalledWith("strat:signal-history");
  });

  it("equity BACKTEST calls runEquityBacktest and shows completed metrics", async () => {
    mockedApi.runEquityBacktest.mockResolvedValue({ run_id: "r1", status: "queued" });
    mockedApi.getBacktestResults.mockResolvedValue({
      status: "completed", total_return_pct: 0.05, sharpe_ratio: 1.2,
      win_rate: 0.6, max_drawdown_pct: 0.03, total_trades: 4,
    });
    render(<BacktestButtons ticker="AAPL" assetType="equity" />);
    fireEvent.click(screen.getByRole("button", { name: /^backtest$/i }));
    expect(mockedApi.runEquityBacktest).toHaveBeenCalledWith(
      expect.objectContaining({ ticker: "AAPL" })
    );
    await waitFor(() => expect(screen.getByText("5.0%")).toBeInTheDocument(), { timeout: 3000 });
  });

  it("options BACKTEST for a non-SPY ticker is disabled and labeled", () => {
    render(<BacktestButtons ticker="AAPL" assetType="options" strategy="bull_put_spread" />);
    const btn = screen.getByRole("button", { name: /spy only/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(mockedApi.runBacktest).not.toHaveBeenCalled();
  });

  it("options BACKTEST for SPY calls runBacktest with the signal's strategy", async () => {
    mockedApi.runBacktest.mockResolvedValue({ run_id: "r2", status: "queued" });
    mockedApi.getBacktestResults.mockResolvedValue({ status: "completed", total_trades: 2 });
    render(<BacktestButtons ticker="SPY" assetType="options" strategy="iron_condor" />);
    fireEvent.click(screen.getByRole("button", { name: /^backtest$/i }));
    expect(mockedApi.runBacktest).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: "iron_condor" })
    );
    await waitFor(() => expect(screen.getByText("TRADES")).toBeInTheDocument(), { timeout: 3000 });
  });
});
