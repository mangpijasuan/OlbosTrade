/**
 * The calendar's job is to report a record honestly, so these pin the ways it
 * could quietly misrepresent one.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import SignalCalendar from "./SignalCalendar";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { getSignalCalendar: vi.fn() } }));
const mocked = api as unknown as { getSignalCalendar: ReturnType<typeof vi.fn> };

const pick = (ticker: string, rank = 1, outcome: string | null = "pending") => ({
  rank, ticker, opportunity_score: 81, confidence: 0.72,
  entry_price: 10, stop_price: 9, target_price: 12,
  outcome, days_to_resolve: outcome === "target_hit" ? 4 : null,
});

beforeEach(() => { vi.clearAllMocks(); });

describe("SignalCalendar", () => {
  it("renders a day's picks per side", async () => {
    mocked.getSignalCalendar.mockResolvedValue({
      status: "ok",
      days: [{ date: "2026-08-31", BUY: [pick("VRTX")], SELL: [pick("XEL")] }],
      summary: { trading_days: 1, picks: 2, resolved: 0, pending: 2, target_hit: 0, hit_rate_pct: null },
    });
    render(<SignalCalendar />);
    expect(await screen.findByText("VRTX")).toBeInTheDocument();
    expect(screen.getByText("XEL")).toBeInTheDocument();
    expect(screen.getByText("2026-08-31")).toBeInTheDocument();
  });

  it("reports pending alongside resolved rather than folding it away", async () => {
    // An unresolved signal is not a miss. Hiding it would understate the
    // record as surely as dropping it would flatter it.
    mocked.getSignalCalendar.mockResolvedValue({
      status: "ok",
      days: [{ date: "2026-08-31", BUY: [pick("VRTX", 1, "target_hit")], SELL: [] }],
      summary: { trading_days: 1, picks: 6, resolved: 1, pending: 5, target_hit: 1, hit_rate_pct: 100 },
    });
    render(<SignalCalendar />);
    await screen.findByText("PENDING");
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("says a side had nothing rather than showing an empty box", async () => {
    mocked.getSignalCalendar.mockResolvedValue({
      status: "ok",
      days: [{ date: "2026-08-31", BUY: [pick("VRTX")], SELL: [] }],
      summary: { trading_days: 1, picks: 1, resolved: 0, pending: 1, target_hit: 0, hit_rate_pct: null },
    });
    render(<SignalCalendar />);
    expect(await screen.findByText("none ranked")).toBeInTheDocument();
  });

  it("shows the backend's own note when there are no snapshots", async () => {
    mocked.getSignalCalendar.mockResolvedValue({
      status: "no_snapshots_yet", days: [],
      note: "Snapshots begin accumulating from the first 10:00 ET capture.",
    });
    render(<SignalCalendar />);
    expect(await screen.findByText(/first 10:00 ET capture/)).toBeInTheDocument();
  });

  it("a fetch failure must not read as an empty record", async () => {
    // "No snapshots" and "could not load" are different facts about the desk.
    mocked.getSignalCalendar.mockRejectedValue(new Error("boom"));
    render(<SignalCalendar />);
    await waitFor(() => expect(screen.getByText(/Could not load/)).toBeInTheDocument());
    expect(screen.queryByText(/No snapshots yet/)).not.toBeInTheDocument();
  });
});
