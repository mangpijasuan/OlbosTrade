import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Landing from "../Landing";

const UNSUPPORTED_CLAIMS = [
  /guaranteed returns?/i,
  /risk-free/i,
  /market-beating/i,
  /passive income/i,
  /proven alpha/i,
  /consistent profits?/i,
];

function renderLanding() {
  return render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>
  );
}

describe("Landing", () => {
  it("renders the hero and primary CTA", () => {
    renderLanding();
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /start paper trading/i }).length).toBeGreaterThan(0);
  });

  it("routes the CTA and Sign In to the existing terminal, not a fabricated auth flow", () => {
    renderLanding();
    const ctas = screen.getAllByRole("link", { name: /start paper trading/i });
    ctas.forEach((cta) => expect(cta).toHaveAttribute("href", "/terminal"));
    const signInLinks = screen.getAllByRole("link", { name: /^sign in$/i });
    expect(signInLinks.length).toBeGreaterThan(0);
    signInLinks.forEach((link) => expect(link).toHaveAttribute("href", "/terminal"));
  });

  it("labels every performance metric as unpublished/placeholder instead of fabricating numbers", () => {
    renderLanding();
    expect(screen.getByText("Not published")).toBeInTheDocument();
    expect(screen.getByText("Demo data")).toBeInTheDocument();
    expect(screen.getAllByText("Awaiting verified history").length).toBeGreaterThanOrEqual(2);
  });

  it("never uses unsupported/guaranteed-return marketing language", () => {
    renderLanding();
    const bodyText = document.body.textContent || "";
    UNSUPPORTED_CLAIMS.forEach((pattern) => {
      expect(bodyText).not.toMatch(pattern);
    });
  });

  it("does not render a fake-functional waitlist form that silently discards input", () => {
    renderLanding();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("exposes footer legal links as explicitly non-functional placeholders, not invented URLs", () => {
    renderLanding();
    const privacy = screen.getByText("Privacy");
    expect(privacy.tagName.toLowerCase()).not.toBe("a");
    expect(privacy).toHaveAttribute("title", "Not published");
  });

  it("mobile nav toggle is keyboard accessible and reports its expanded state", () => {
    renderLanding();
    const toggle = screen.getByRole("button", { name: /open menu/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
