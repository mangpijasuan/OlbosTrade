import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import ManualTradePanel from "../ManualTradePanel";

// HoldToConfirmButton drives its progress off performance.now()/rAF. Mocking
// both lets a single mouseDown "complete" a full hold synchronously instead
// of fighting real timing in tests — see the plan's note on this tradeoff.
function mockCompletedHold() {
  let now = 0;
  vi.stubGlobal("performance", { now: () => now } as any);
  vi.stubGlobal("requestAnimationFrame", ((cb: FrameRequestCallback) => {
    now += 5000; // jumps well past any holdMs used in this file
    cb(now);
    return 1;
  }) as any);
  vi.stubGlobal("cancelAnimationFrame", (() => {}) as any);
}

describe("ManualTradePanel", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ result: "submitted", ticker: "AAPL", order_id: "o1", order_status: "filled", entry_price: 190.12 }),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders ticker, side, shares, and order type fields, with limit price hidden by default", () => {
    render(<ManualTradePanel />);
    expect(screen.getByPlaceholderText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("SIDE")).toBeInTheDocument();
    expect(screen.getByText("SHARES")).toBeInTheDocument();
    expect(screen.getByText("ORDER TYPE")).toBeInTheDocument();
    expect(screen.queryByText("LIMIT PRICE")).not.toBeInTheDocument();
  });

  it("shows the limit price field only when order type is limit", () => {
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByDisplayValue("MARKET"), { target: { value: "limit" } });
    expect(screen.getByText("LIMIT PRICE")).toBeInTheDocument();
  });

  it("a single click (mouseDown immediately followed by mouseUp) does not submit an order", () => {
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByPlaceholderText("AAPL"), { target: { value: "aapl" } });
    const holdButton = screen.getByText("HOLD TO SUBMIT ORDER");
    fireEvent.mouseDown(holdButton);
    fireEvent.mouseUp(holdButton);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects a shares value above the client-side sanity cap without a network call", () => {
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByPlaceholderText("AAPL"), { target: { value: "aapl" } });
    const sharesInput = screen.getByDisplayValue("10");
    fireEvent.change(sharesInput, { target: { value: "50000" } });
    expect(screen.getByText(/exceeds the 10,000-share sanity limit/i)).toBeInTheDocument();
    mockCompletedHold();
    fireEvent.mouseDown(screen.getByText("HOLD TO SUBMIT ORDER"));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("submits the correct body to the manual-trade endpoint on a completed hold", async () => {
    mockCompletedHold();
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByPlaceholderText("AAPL"), { target: { value: "aapl" } });
    fireEvent.mouseDown(screen.getByText("HOLD TO SUBMIT ORDER"));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, opts] = (fetch as any).mock.calls[0];
    expect(url).toBe("/api/trade-desk/manual-trade");
    expect(opts.method).toBe("POST");
    const body = JSON.parse(opts.body);
    expect(body).toEqual({ ticker: "AAPL", action: "BUY", shares: 10, order_type: "market", limit_price: null });
  });

  it("renders a submitted result distinctly", async () => {
    mockCompletedHold();
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByPlaceholderText("AAPL"), { target: { value: "aapl" } });
    fireEvent.mouseDown(screen.getByText("HOLD TO SUBMIT ORDER"));
    expect(await screen.findByText("SUBMITTED")).toBeInTheDocument();
    expect(screen.getByText(/order o1 \(filled\)/i)).toBeInTheDocument();
  });

  it("renders a blocked result distinctly, worded as a guardrail rather than a failure", async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ result: "blocked", reason: "kill_switch" }),
    });
    mockCompletedHold();
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByPlaceholderText("AAPL"), { target: { value: "aapl" } });
    fireEvent.mouseDown(screen.getByText("HOLD TO SUBMIT ORDER"));
    expect(await screen.findByText("BLOCKED")).toBeInTheDocument();
    expect(screen.getByText(/Blocked by risk guardrails: kill_switch/i)).toBeInTheDocument();
  });

  it("renders a skipped result distinctly", async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ result: "skipped", reason: "duplicate_position" }),
    });
    mockCompletedHold();
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByPlaceholderText("AAPL"), { target: { value: "aapl" } });
    fireEvent.mouseDown(screen.getByText("HOLD TO SUBMIT ORDER"));
    expect(await screen.findByText("SKIPPED")).toBeInTheDocument();
    expect(screen.getByText(/Blocked by risk guardrails: duplicate_position/i)).toBeInTheDocument();
  });

  it("renders the error detail from a failed HTTP response", async () => {
    (fetch as any).mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: "broker connection lost" }),
    });
    mockCompletedHold();
    render(<ManualTradePanel />);
    fireEvent.change(screen.getByPlaceholderText("AAPL"), { target: { value: "aapl" } });
    fireEvent.mouseDown(screen.getByText("HOLD TO SUBMIT ORDER"));
    expect(await screen.findByText("broker connection lost")).toBeInTheDocument();
  });
});
