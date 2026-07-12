import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import SignalDivergence from "../SignalDivergence";

describe("SignalDivergence", () => {
  it("renders nothing when either signal is missing", () => {
    const { container } = render(
      <SignalDivergence symbol="SPY" signalA={{ direction: "BUY" }} signalB={null} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when both signals agree", () => {
    const { container } = render(
      <SignalDivergence
        symbol="SPY"
        signalA={{ direction: "BUY", timeframe: "Daily" }}
        signalB={{ direction: "BULLISH", timeframe: "Daily" }}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("flags a hard conflict as Signal divergence", () => {
    render(
      <SignalDivergence
        symbol="SPY"
        signalA={{ direction: "BUY", source: "Equity Scan Engine" }}
        signalB={{ direction: "SELL", source: "Options Scan Engine" }}
      />
    );
    expect(screen.getByText("Signal divergence")).toBeInTheDocument();
    expect(screen.getByText("SPY")).toBeInTheDocument();
  });

  it("flags one directional + one neutral signal as Mixed confirmation", () => {
    render(
      <SignalDivergence
        symbol="QQQ"
        signalA={{ direction: "BUY" }}
        signalB={{ direction: "HOLD" }}
      />
    );
    expect(screen.getByText("Mixed confirmation")).toBeInTheDocument();
  });

  it("flags same-direction, different-timeframe as Timeframe disagreement", () => {
    render(
      <SignalDivergence
        symbol="SPY"
        signalA={{ direction: "BUY", timeframe: "Daily" }}
        signalB={{ direction: "BUY", timeframe: "Weekly" }}
      />
    );
    expect(screen.getByText("Timeframe disagreement")).toBeInTheDocument();
  });

  it("never claims which signal controls execution when authority is unknown", () => {
    render(
      <SignalDivergence
        symbol="SPY"
        signalA={{ direction: "BUY" }}
        signalB={{ direction: "SELL" }}
      />
    );
    // Both the divergence note and each signal's own attribution disclosure
    // agree that authority is unknown — assert it's stated, not guessed.
    expect(
      screen.getAllByText("Execution authority is not available from the current frontend data.").length
    ).toBeGreaterThan(0);
  });
});
