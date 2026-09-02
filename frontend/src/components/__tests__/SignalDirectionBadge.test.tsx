/**
 * The rule: a side chip only earns its space when it says something the
 * action does not. "BUY LONG" and "SELL SHORT" are one fact printed twice.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import SignalDirectionBadge from "../SignalDirectionBadge";

describe("SignalDirectionBadge", () => {
  it("shows BUY alone — the action already implies LONG", () => {
    render(<SignalDirectionBadge action="BUY" />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
  });

  it("shows SELL alone — the action already implies SHORT", () => {
    render(<SignalDirectionBadge action="SELL" />);
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.queryByText("SHORT")).not.toBeInTheDocument();
  });

  it("stays silent when the supplied side merely agrees with the action", () => {
    // A caller passing the redundant value explicitly must not resurrect it.
    render(<SignalDirectionBadge action="BUY" positionDirection="LONG" />);
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
  });

  it("accepts the side in the action's own vocabulary and still stays silent", () => {
    render(<SignalDirectionBadge action="BUY" positionDirection="BUY" />);
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
  });

  it("shows the side when it genuinely disagrees — buying back a short", () => {
    // This is the case the chip exists for and the one that must survive.
    render(<SignalDirectionBadge action="BUY" positionDirection="SHORT" />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SHORT")).toBeInTheDocument();
  });

  it("shows the side when selling out of a long", () => {
    render(<SignalDirectionBadge action="SELL" positionDirection="LONG" />);
    expect(screen.getByText("LONG")).toBeInTheDocument();
  });

  it("honours an explicit showSide=false even on a disagreement", () => {
    render(
      <SignalDirectionBadge action="BUY" positionDirection="SHORT" showSide={false} />,
    );
    expect(screen.queryByText("SHORT")).not.toBeInTheDocument();
  });

  it("renders nothing without an action", () => {
    const { container } = render(<SignalDirectionBadge action={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("maps spread actions the same way", () => {
    render(<SignalDirectionBadge action="BUY_SPREAD" positionDirection="LONG" />);
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
  });
});
