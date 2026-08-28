/**
 * The panel exists so an operator reads before clicking. These tests pin the
 * parts that make that true: uncalibrated numbers must be labelled as such,
 * the excluded sunk cost must be visibly excluded rather than merely absent,
 * and a failed approve must lead with the fact that nothing was closed.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import RotationReviewPanel, { RotationReviewEntry } from "./RotationReviewPanel";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { approveRotationReview: vi.fn(), rejectRotationReview: vi.fn() },
}));

const entry = (over: Partial<RotationReviewEntry> = {}): RotationReviewEntry => ({
  review_id: "rev-1",
  ticker: "TSLA",
  incumbent_trade_id: "trade-1",
  queued_at: "2026-08-28T19:00:00Z",
  review: {
    recommendation: "replace",
    reasons: ["challenger composite 78.0 vs incumbent 41.0 = +37.0"],
    incumbent: {
      ticker: "MRVL", composite: 41, alpha_edge: 38, quality_score: 41,
      confidence: 0.62, p_target_before_stop: 0.33, in_flagged_cluster: false,
      unrealized_pnl_context_only: -11239.22,
    },
    challenger: {
      ticker: "TSLA", composite: 78, alpha_edge: 74, quality_score: null,
      confidence: 0.95, p_target_before_stop: 0.33, in_flagged_cluster: false,
    },
    composite_margin: 37,
    materiality_margin: 15,
    sunk_cost_excluded: true,
  },
  ...over,
});

beforeEach(() => { vi.clearAllMocks(); });

describe("RotationReviewPanel", () => {
  it("labels every heuristic as uncalibrated", () => {
    render(<RotationReviewPanel reviews={[entry()]} />);
    // One per heuristic row: composite, alpha edge, quality, confidence.
    expect(screen.getAllByText("UNCAL")).toHaveLength(4);
  });

  it("states that Expected R was not computed rather than omitting it", () => {
    render(<RotationReviewPanel reviews={[entry()]} />);
    expect(screen.getByText(/Expected R:/)).toBeInTheDocument();
    expect(screen.getByText(/no calibrated probability model/)).toBeInTheDocument();
  });

  it("shows the incumbent's loss but marks it excluded from the decision", () => {
    render(<RotationReviewPanel reviews={[entry()]} />);
    expect(screen.getByText("-$11,239.22")).toBeInTheDocument();
    expect(screen.getByText(/Sunk cost excluded/)).toBeInTheDocument();
    expect(screen.getByText(/incurred whether or not the/)).toBeInTheDocument();
  });

  it("rejects without any approve call", async () => {
    const onResolved = vi.fn();
    render(<RotationReviewPanel reviews={[entry()]} onResolved={onResolved} />);
    fireEvent.click(screen.getByText("REJECT"));
    await waitFor(() => expect(api.rejectRotationReview).toHaveBeenCalledWith("rev-1"));
    expect(api.approveRotationReview).not.toHaveBeenCalled();
    expect(onResolved).toHaveBeenCalled();
  });

  it("leads a 403 with the fact that nothing was closed", async () => {
    (api.rejectRotationReview as any).mockRejectedValue(new Error("API error 403: Forbidden"));
    render(<RotationReviewPanel reviews={[entry()]} />);
    fireEvent.click(screen.getByText("REJECT"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/^REFUSED — nothing closed/);
    expect(alert.textContent).toMatch(/Operator API Key/);
  });

  it("reports a stale review as nothing-closed too", async () => {
    (api.rejectRotationReview as any).mockRejectedValue(new Error("API error 409: Conflict"));
    render(<RotationReviewPanel reviews={[entry()]} />);
    fireEvent.click(screen.getByText("REJECT"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/^STALE — nothing closed/);
  });

  it("disables approve when there is no incumbent to close", () => {
    render(<RotationReviewPanel reviews={[entry({
      incumbent_trade_id: null,
      review: { ...entry().review, recommendation: "insufficient_data" },
    })]} />);
    expect(screen.getByText(/APPROVE \(not recommended\)/).closest("button")).toBeDisabled();
  });

  it("renders an explicit empty state", () => {
    render(<RotationReviewPanel reviews={[]} />);
    expect(screen.getByText(/No rotation reviews awaiting approval/)).toBeInTheDocument();
  });
});
