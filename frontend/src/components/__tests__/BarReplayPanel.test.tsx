import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

import BarReplayPanel from "../BarReplayPanel";

function barLog() {
  return [
    { date: "2024-01-02", close: 100, indicators: null, action: "HOLD",
      confidence: null, trade_fired: false, position_open: false, portfolio_value: 25000 },
    { date: "2024-01-03", close: 101,
      indicators: { rsi: 55, macd: 0.1, bb_pct_b: 0.6, atr: 1.2, volume_ratio: 1.1 },
      action: "BUY", confidence: 0.8, trade_fired: true, position_open: true, portfolio_value: 25000 },
    { date: "2024-01-04", close: 102,
      indicators: { rsi: 58, macd: 0.2, bb_pct_b: 0.65, atr: 1.3, volume_ratio: 1.0 },
      action: "HOLD", confidence: 0.5, trade_fired: false, position_open: true, portfolio_value: 25100 },
  ];
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("BarReplayPanel", () => {
  it("renders nothing for an empty bar_log", () => {
    const { container } = render(<BarReplayPanel barLog={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("starts at the first bar and disables PREV", () => {
    render(<BarReplayPanel barLog={barLog()} />);
    expect(screen.getByText("2024-01-02")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^prev$/i })).toBeDisabled();
    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("NEXT/PREV step through bars and surface indicator values", () => {
    render(<BarReplayPanel barLog={barLog()} />);
    fireEvent.click(screen.getByRole("button", { name: /^next$/i }));
    expect(screen.getByText("2024-01-03")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("55.00")).toBeInTheDocument(); // rsi
    expect(screen.getByText("● TRADE FIRED")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^prev$/i }));
    expect(screen.getByText("2024-01-02")).toBeInTheDocument();
  });

  it("NEXT is disabled on the last bar", () => {
    render(<BarReplayPanel barLog={barLog()} />);
    fireEvent.click(screen.getByRole("button", { name: /^next$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^next$/i }));
    expect(screen.getByText("3/3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
  });

  it("PLAY advances the index automatically and stops at the end", () => {
    render(<BarReplayPanel barLog={barLog()} />);
    fireEvent.click(screen.getByRole("button", { name: /^play$/i }));
    expect(screen.getByRole("button", { name: /^pause$/i })).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(400); });
    expect(screen.getByText("2/3")).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(400); });
    // Playback stops as soon as it reaches the last bar — button reverts to PLAY.
    expect(screen.getByText("3/3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^play$/i })).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(400); });
    expect(screen.getByText("3/3")).toBeInTheDocument();
  });

  it("PAUSE stops automatic advancement", () => {
    render(<BarReplayPanel barLog={barLog()} />);
    fireEvent.click(screen.getByRole("button", { name: /^play$/i }));
    act(() => { vi.advanceTimersByTime(400); });
    expect(screen.getByText("2/3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^pause$/i }));
    act(() => { vi.advanceTimersByTime(1200); });
    expect(screen.getByText("2/3")).toBeInTheDocument();
  });
});
