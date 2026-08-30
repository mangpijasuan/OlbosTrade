/**
 * The bug this pins: `refresh` set loading=true on every 10s poll, so the
 * queue tore down all its rendered rows and showed skeletons on every cycle.
 * With 174 pending cards the re-render made that window long enough that the
 * panel looked permanently empty.
 *
 * Skeletons are honest on first paint and dishonest on a background refresh —
 * the data is already on screen and still valid.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

import CopilotQueue from "./CopilotQueue";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: {
    getPendingApprovals: vi.fn(),
    getExecutionLog: vi.fn(),
    getExecutionMode: vi.fn(),
    approveSignal: vi.fn(),
    rejectSignal: vi.fn(),
  },
}));

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const signal = (ticker: string) => ({
  id: `id-${ticker}`, ticker, action: "SELL", asset_type: "equity",
  confidence: 0.3788, source: "Equity Signal Scanner",
  regime: "low_vol_trending", queued_at: "2026-08-28T19:45:26Z",
  trade_plan: { entry_price: 141.02, stop_price: 158.03, target_price: 107.01 },
});

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.getPendingApprovals.mockResolvedValue({
    pending: [signal("SPCX"), signal("DDOG")], mode: "autopilot",
  });
  mockedApi.getExecutionLog.mockResolvedValue({ log: [] });
  mockedApi.getExecutionMode.mockResolvedValue({ mode: "autopilot" });
});

afterEach(() => { vi.useRealTimers(); });

describe("CopilotQueue", () => {
  it("renders the pending signals once loaded", async () => {
    render(<CopilotQueue />);
    expect(await screen.findByText("SPCX")).toBeInTheDocument();
    expect(screen.getByText("DDOG")).toBeInTheDocument();
  });

  it("keeps the rows on screen across a background poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CopilotQueue />);
    await waitFor(() => expect(screen.getByText("SPCX")).toBeInTheDocument());

    // Hold the next fetch open so the poll is mid-flight when we assert —
    // exactly the window in which the old code showed skeletons.
    let release: (v: unknown) => void = () => {};
    mockedApi.getPendingApprovals.mockReturnValueOnce(
      new Promise((res) => { release = res; }),
    );

    await act(async () => { vi.advanceTimersByTime(10_000); });

    // The already-valid data must still be on screen mid-refresh.
    expect(screen.getByText("SPCX")).toBeInTheDocument();
    expect(screen.getByText("DDOG")).toBeInTheDocument();

    await act(async () => {
      release({ pending: [signal("SPCX"), signal("DDOG")], mode: "autopilot" });
    });
    expect(screen.getByText("SPCX")).toBeInTheDocument();
  });

  it("still refetches on the poll — the fix suppresses the skeleton, not the request", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CopilotQueue />);
    await waitFor(() => expect(screen.getByText("SPCX")).toBeInTheDocument());
    const callsAfterFirstLoad = mockedApi.getPendingApprovals.mock.calls.length;

    await act(async () => { vi.advanceTimersByTime(10_000); });
    expect(mockedApi.getPendingApprovals.mock.calls.length)
      .toBeGreaterThan(callsAfterFirstLoad);
  });

  it("reflects a signal disappearing from the queue after a poll", async () => {
    // The list must still be live — suppressing the skeleton must not freeze it.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CopilotQueue />);
    await waitFor(() => expect(screen.getByText("DDOG")).toBeInTheDocument());

    mockedApi.getPendingApprovals.mockResolvedValue({
      pending: [signal("SPCX")], mode: "autopilot",
    });
    await act(async () => { vi.advanceTimersByTime(10_000); });

    await waitFor(() => expect(screen.queryByText("DDOG")).not.toBeInTheDocument());
    expect(screen.getByText("SPCX")).toBeInTheDocument();
  });
});
