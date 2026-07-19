import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import WelcomeBanner from "../WelcomeBanner";
import { TerminalNavProvider } from "../TerminalNavContext";

describe("WelcomeBanner", () => {
  it("renders three getting-started steps and navigates via TerminalNav", () => {
    const onNav = vi.fn();
    const onDismiss = vi.fn();
    render(
      <TerminalNavProvider onNav={onNav}>
        <WelcomeBanner onDismiss={onDismiss} />
      </TerminalNavProvider>,
    );

    expect(screen.getByLabelText(/getting started/i)).toBeInTheDocument();
    expect(screen.getByText(/three steps before you trade/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open broker/i }));
    expect(onNav).toHaveBeenCalledWith("system:broker");

    fireEvent.click(screen.getByRole("button", { name: /open signals/i }));
    expect(onNav).toHaveBeenCalledWith("equity");

    fireEvent.click(screen.getByRole("button", { name: /dismiss welcome/i }));
    expect(onDismiss).toHaveBeenCalled();
  });
});
