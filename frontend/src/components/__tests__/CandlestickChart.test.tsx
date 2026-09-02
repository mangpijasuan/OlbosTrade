import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

// jsdom has no real canvas context — mock lightweight-charts entirely rather
// than mounting the real chart. This mirrors the project's existing pattern
// of not visually rendering canvas output in unit tests (see Dashboard.tsx's
// EquityChart, which also has no test rendering its canvas).
const mockSeries = {
  setData: vi.fn(),
  createPriceLine: vi.fn(() => ({})),
  removePriceLine: vi.fn(),
  priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
};
const mockChart = {
  addSeries: vi.fn(() => mockSeries),
  remove: vi.fn(),
  timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
};

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => mockChart),
  CandlestickSeries: "CandlestickSeries",
  HistogramSeries: "HistogramSeries",
  LineSeries: "LineSeries",
}));

import CandlestickChart, {
  toUnixSeconds,
  barsToCandlestickData,
  barsToVolumeData,
  type ChartBar,
} from "../CandlestickChart";

const sampleBars: ChartBar[] = [
  { timestamp: "2026-08-14T09:30:00-04:00", open: 100, high: 102, low: 99, close: 101, volume: 1000 },
  { timestamp: "2026-08-14T09:45:00-04:00", open: 101, high: 101.5, low: 98, close: 98.5, volume: 2000 },
];

describe("data-mapping functions (pure, no DOM)", () => {
  it("toUnixSeconds converts an ISO timestamp to UNIX seconds", () => {
    expect(toUnixSeconds("2026-08-14T09:30:00-04:00")).toBe(Math.floor(new Date("2026-08-14T09:30:00-04:00").getTime() / 1000));
  });

  it("barsToCandlestickData maps OHLC fields and converts time", () => {
    const data = barsToCandlestickData(sampleBars);
    expect(data).toHaveLength(2);
    expect(data[0]).toMatchObject({ open: 100, high: 102, low: 99, close: 101 });
    expect(data[0].time).toBe(toUnixSeconds(sampleBars[0].timestamp));
  });

  it("barsToVolumeData colors up bars green and down bars red", () => {
    const data = barsToVolumeData(sampleBars);
    expect(data[0]).toMatchObject({ value: 1000, color: "rgba(24,195,126,0.32)" }); // close >= open
    expect(data[1]).toMatchObject({ value: 2000, color: "rgba(255,95,109,0.32)" }); // close < open
  });
});

describe("CandlestickChart component", () => {
  it("shows the empty state when there are no bars", () => {
    render(<CandlestickChart bars={[]} levels={[]} />);
    expect(screen.getByText("NO CHART DATA")).toBeInTheDocument();
  });

  it("creates the chart and four series (candles, volume, SMA, VWAP) on mount", () => {
    cleanup();
    mockChart.addSeries.mockClear();
    mockSeries.setData.mockClear();
    render(<CandlestickChart bars={sampleBars} levels={[]} />);
    expect(mockChart.addSeries).toHaveBeenCalledTimes(4);
    expect(mockSeries.setData).toHaveBeenCalled();
  });

  it("draws a price line per support/resistance level", () => {
    cleanup();
    mockSeries.createPriceLine.mockClear();
    render(
      <CandlestickChart
        bars={sampleBars}
        levels={[{ label: "R1", value: 105, color: "#f00" }, { label: "S1", value: 95, color: "#0f0" }]}
      />,
    );
    expect(mockSeries.createPriceLine).toHaveBeenCalledTimes(2);
  });

  it("removes the chart on unmount", () => {
    cleanup();
    mockChart.remove.mockClear();
    const { unmount } = render(<CandlestickChart bars={sampleBars} levels={[]} />);
    unmount();
    expect(mockChart.remove).toHaveBeenCalledTimes(1);
  });
});
