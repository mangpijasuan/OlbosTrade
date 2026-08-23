import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import TerminalLayout from "../TerminalLayout";

vi.mock("../../api/client", () => ({
  api: {
    getExecutionMode: vi.fn().mockResolvedValue({ mode: "manual" }),
    setExecutionMode: vi.fn().mockResolvedValue({ mode: "manual" }),
    getCurrentMode: vi.fn().mockResolvedValue({ mode: "balanced" }),
    getGuardrailStatus: vi.fn().mockResolvedValue({
      trading_allowed: true,
      paper_mode: true,
      position_rotation_on_max: false,
    }),
    getTradeDeskKillSwitch: vi.fn().mockResolvedValue({ engaged: false }),
    getKillSwitchStatus: vi.fn().mockResolvedValue({ engaged: false }),
    setTradeDeskKillSwitch: vi.fn().mockResolvedValue({ engaged: true }),
    getPortfolioState: vi.fn().mockResolvedValue({ state: {} }),
  },
}));

// Regression test for a real crash found via live-backend verification: when
// /api/market/snapshot/{symbol} errors out (a documented yfinance-failure
// condition, see AUDIT_2026-06.md), the JSON payload omits last_close /
// change_pct entirely, so they arrive as `undefined` rather than `null`.
// TickerCell used to check `price !== null`, which is true for `undefined`,
// so it called `.toFixed()` on `undefined` and crashed the whole terminal
// shell with no error boundary catching it.
describe("TerminalLayout ticker strip", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/market/snapshot/")) {
        // Real error-shape payload observed from the backend: no last_close/
        // prev_close/change_pct fields at all.
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ symbol: "SPY", error: "No data returned" }),
        });
      }
      if (url.includes("/api/market/regime")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }
      if (url.includes("/api/mode/current")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ mode: "balanced" }) });
      }
      if (url.includes("/api/trade-desk/execution-mode")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ mode: "manual" }) });
      }
      if (url.includes("/api/market/broker")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ broker: "ibkr", paper_mode: true, status: "disconnected" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    // Not restoreAllMocks(): that would wipe the mockResolvedValue set on
    // the module-level api.* vi.fn()s from the vi.mock() factory above,
    // leaving them returning undefined in later tests within this file.
    vi.clearAllMocks();
  });

  it("renders '—' instead of crashing when a snapshot payload has no price fields", async () => {
    render(
      <TerminalLayout activePage="dashboard" onNav={() => {}}>
        <div>page content</div>
      </TerminalLayout>
    );

    // The shell must still render — no "failed to render" error boundary
    // fallback, and the actual page content underneath is reachable.
    await waitFor(() => expect(screen.getByText("page content")).toBeInTheDocument());
    expect(screen.queryByText(/failed to render/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("does not crash when /api/market/regime returns a payload without a regime field", async () => {
    // The mocked regime response in beforeEach is `{}` — a truthy object
    // with no `.regime` string, reproducing the second half of the same bug
    // class (regime.regime.includes()/.replace() on undefined).
    render(
      <TerminalLayout activePage="dashboard" onNav={() => {}}>
        <div>page content</div>
      </TerminalLayout>
    );

    await waitFor(() => expect(screen.getByText("page content")).toBeInTheDocument());
    expect(screen.queryByText(/failed to render/i)).not.toBeInTheDocument();
    expect(screen.queryByText("REGIME")).not.toBeInTheDocument();
  });

  it("shows a human status label for the active page, not a hardcoded TRADE DESK", async () => {
    render(
      <TerminalLayout activePage="markets:chart" onNav={() => {}}>
        <div>page content</div>
      </TerminalLayout>
    );

    await waitFor(() => expect(screen.getByText("page content")).toBeInTheDocument());
    expect(screen.getByText("MARKETS · CHART")).toBeInTheDocument();
    // The old bug was a second status span always reading TRADE DESK.
    const matches = screen.queryAllByText("TRADE DESK");
    expect(matches.length).toBe(0);
  });

  it("renders a tri-state execution mode control instead of dual ON/OFF chips", async () => {
    render(
      <TerminalLayout activePage="dashboard" onNav={() => {}}>
        <div>page content</div>
      </TerminalLayout>
    );

    await waitFor(() => expect(screen.getByText("page content")).toBeInTheDocument());
    const modeGroup = screen.getByRole("group", { name: /execution mode/i });
    expect(modeGroup).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^manual$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^copilot$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^autopilot$/i })).toBeInTheDocument();
    // Old dual chips were "COPILOT ON" / "AUTOPILOT OFF" inside the header control.
    expect(modeGroup).not.toHaveTextContent(/COPILOT ON/i);
    expect(modeGroup).not.toHaveTextContent(/AUTOPILOT OFF/i);
  });

  it("sidebar kill switch engages confirm dialog instead of navigating to risk", async () => {
    const onNav = vi.fn();
    render(
      <TerminalLayout activePage="dashboard" onNav={onNav}>
        <div>page content</div>
      </TerminalLayout>
    );

    await waitFor(() => expect(screen.getByText("page content")).toBeInTheDocument());
    const kill = screen.getByRole("button", { name: /engage kill switch/i });
    fireEvent.click(kill);
    expect(onNav).not.toHaveBeenCalledWith("risk");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/engage kill switch\?/i)).toBeInTheDocument();
  });
});
