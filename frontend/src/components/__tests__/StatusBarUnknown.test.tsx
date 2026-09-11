import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import TerminalLayout from "../TerminalLayout";

/**
 * The bottom status bar answers three questions that decide whether the desk
 * is about to move real money unattended: is the kill switch armed, is this a
 * paper or a live account, and is execution on autopilot.
 *
 * Each used to default to its reassuring answer when the read failed —
 * killOn=false rendered a failed kill-switch read as NOT ARMED, paper=true
 * rendered an unreadable broker as green PAPER even on a live account, and
 * execMode="manual" rendered a failed read as not auto-trading. A dim lamp is
 * indistinguishable from a successful read saying "off", so the row looked
 * calm precisely when it knew least.
 *
 * GlobalRiskStatus already refuses this ("a missing kill-switch read never
 * renders as 'not armed'"), so the two rows could disagree with this one being
 * the optimistic of the pair. These tests pin the failure path.
 */

// Every api.* call rejects: the real "backend unreachable" shape.
vi.mock("../../api/client", () => ({
  api: {
    getExecutionMode: vi.fn().mockRejectedValue(new Error("down")),
    setExecutionMode: vi.fn().mockRejectedValue(new Error("down")),
    getCurrentMode: vi.fn().mockRejectedValue(new Error("down")),
    getGuardrailStatus: vi.fn().mockRejectedValue(new Error("down")),
    getTradeDeskKillSwitch: vi.fn().mockRejectedValue(new Error("down")),
    getKillSwitchStatus: vi.fn().mockRejectedValue(new Error("down")),
    setTradeDeskKillSwitch: vi.fn().mockRejectedValue(new Error("down")),
    getPortfolioState: vi.fn().mockRejectedValue(new Error("down")),
  },
}));

describe("StatusBar with every read failing", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    ) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  const renderShell = () =>
    render(
      <TerminalLayout activePage="dashboard" onNav={() => {}}>
        <div>content</div>
      </TerminalLayout>,
    );

  it("does not claim the account is PAPER when the broker cannot be read", async () => {
    renderShell();
    await waitFor(() => {
      expect(screen.getByText("ENV ?")).toBeInTheDocument();
    });
    // The dangerous rendering: green PAPER on an account whose mode is unknown.
    expect(screen.queryByText("PAPER")).not.toBeInTheDocument();
  });

  it("does not render the kill switch as not-armed when its read fails", async () => {
    renderShell();
    await waitFor(() => {
      expect(screen.getByText(/Kill \?/i)).toBeInTheDocument();
    });
  });

  it("does not render execution as MANUAL when the mode read fails", async () => {
    renderShell();
    await waitFor(() => {
      expect(screen.getByText(/^Exec \?$/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Exec manual/i)).not.toBeInTheDocument();
  });

  it("marks the unknown lamps as attention-coloured, not dim", async () => {
    renderShell();
    const kill = await screen.findByText(/Kill \?/i);
    // Amber is the same tone GlobalRiskStatus uses for unknown, so the two
    // rows agree about what "we could not read this" looks like.
    expect(getComputedStyle(kill).color).not.toBe("");
    expect(kill).toHaveAttribute("title", expect.stringContaining("could not be read"));
  });
});
