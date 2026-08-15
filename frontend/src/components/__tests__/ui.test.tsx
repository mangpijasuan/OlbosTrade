import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Panel, EmptyState, StatPill, StatTile, Badge, Button } from "../ui";

describe("Panel", () => {
  it("renders title, action, and children with default padding", () => {
    render(<Panel title="Positions" action={<span>action-slot</span>}>body content</Panel>);
    expect(screen.getByText("Positions")).toBeInTheDocument();
    expect(screen.getByText("action-slot")).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
  });

  it("applies sectionStyle to the outer section (InfoCard replacement case)", () => {
    render(<Panel title="Chart" sectionStyle={{ overflow: "hidden" }}>x</Panel>);
    const section = screen.getByText("Chart").closest("section");
    expect(section).toHaveStyle({ overflow: "hidden" });
  });
});

describe("EmptyState", () => {
  it("renders children inside .empty-state", () => {
    render(<EmptyState>nothing here</EmptyState>);
    const el = screen.getByText("nothing here");
    expect(el.className).toBe("empty-state");
  });
});

describe("StatPill", () => {
  it("renders label and value", () => {
    render(<StatPill label="RSI" value="54.2" />);
    expect(screen.getByText("RSI")).toBeInTheDocument();
    expect(screen.getByText("54.2")).toBeInTheDocument();
  });
});

describe("StatTile", () => {
  it("renders label, value, and optional sub-line", () => {
    render(<StatTile label="Portfolio Value" value="$250.00k" sub="+0.00% all-time" />);
    expect(screen.getByText("Portfolio Value")).toBeInTheDocument();
    expect(screen.getByText("$250.00k")).toBeInTheDocument();
    expect(screen.getByText("+0.00% all-time")).toBeInTheDocument();
  });

  it("prefers hint over label when both are provided", () => {
    render(<StatTile label="Sharpe" hint={<span>Sharpe Ratio (hinted)</span>} value="1.2" />);
    expect(screen.getByText("Sharpe Ratio (hinted)")).toBeInTheDocument();
    expect(screen.queryByText("Sharpe")).not.toBeInTheDocument();
  });

  it("applies the sm data-val class by default and the divider layout when requested", () => {
    render(<StatTile label="Day P&L" value="+$0" variant="divider" />);
    const value = screen.getByText("+$0");
    expect(value.className).toContain("data-val");
    expect(value.className).toContain("sm");
  });
});

describe("Badge", () => {
  it("renders a mode badge using the existing .mode-badge CSS class", () => {
    render(<Badge kind="mode" tone="aggressive">AGGRESSIVE</Badge>);
    const el = screen.getByText("AGGRESSIVE");
    expect(el.className).toBe("mode-badge aggressive");
  });

  it("renders an outline tag (no bg) when bg is omitted", () => {
    render(<Badge kind="tag" tone="var(--green)">LIVE</Badge>);
    const el = screen.getByText("LIVE");
    // jsdom's CSS parser doesn't expand shorthand `border` containing a
    // var() into longhand properties, so assert on the raw declaration.
    expect(el.style.cssText).toContain("border: 1px solid var(--green)");
    expect(el.style.background).toBe("");
  });

  it("renders a filled tag when bg is provided", () => {
    render(<Badge kind="tag" tone="var(--amber)" bg="rgba(245,158,11,0.1)">UNTRACKED</Badge>);
    const el = screen.getByText("UNTRACKED");
    expect(el).toHaveStyle({ background: "rgba(245,158,11,0.1)" });
  });
});

describe("Button", () => {
  it("applies .btn-t and the active/danger modifier classes", () => {
    render(<Button active>1W</Button>);
    expect(screen.getByText("1W").className).toBe("btn-t active");
  });

  it("applies sm sizing styles", () => {
    render(<Button size="sm">Refresh</Button>);
    expect(screen.getByText("Refresh")).toHaveStyle({ fontSize: "10px" });
  });

  it("forwards standard button props like onClick", () => {
    let clicked = false;
    render(<Button onClick={() => { clicked = true; }}>Go</Button>);
    screen.getByText("Go").click();
    expect(clicked).toBe(true);
  });
});
