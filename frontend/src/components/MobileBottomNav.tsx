/**
 * Thumb-reachable primary navigation for phones.
 *
 * The shell already had an overlay sidebar, but every navigation started with
 * a reach to a hamburger in the top-left — the furthest point from a thumb on
 * a phone held one-handed. This puts the five destinations that carry the
 * live money path within reach, and leaves the sidebar for everything else.
 *
 * Five, not more: a sixth tab drops each target below the 44px that a finger
 * actually needs. The overflow lives behind "More", which opens the existing
 * sidebar rather than inventing a second navigation surface.
 *
 * Deliberately not a router — it calls the same onNav the sidebar does, so
 * active state and page resolution stay in one place.
 */

import React from "react";

export type BottomNavItem = {
  key: string;
  label: string;
  /** Nav keys that should light this tab up, beyond `key` itself. */
  matches?: string[];
  icon: React.ReactNode;
};

// 24px line icons — stroke, not fill, to sit with the terminal's type weight.
const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

const Icon = ({ children }: { children: React.ReactNode }) => (
  <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
    {children}
  </svg>
);

export const BOTTOM_NAV_ITEMS: BottomNavItem[] = [
  {
    key: "dashboard",
    label: "Home",
    icon: <Icon><path d="M3 10.5 12 4l9 6.5" /><path d="M5.5 9.5V20h13V9.5" /></Icon>,
  },
  {
    key: "trade:overview",
    label: "Desk",
    matches: ["trade:orders", "trade:copilot", "trade:execlog", "trade:logs"],
    icon: <Icon><path d="M4 18V9" /><path d="M9.5 18V5" /><path d="M15 18v-6" /><path d="M20.5 18V8" /></Icon>,
  },
  {
    key: "equity",
    label: "Signals",
    matches: ["options:signals", "strat:alpha-edge", "strat:research"],
    icon: <Icon><path d="M3 13.5h4l3-7 4 13 3-6.5h4" /></Icon>,
  },
  {
    key: "trade:positions",
    label: "Positions",
    icon: <Icon><rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M3.5 10h17" /><path d="M9 10v9" /></Icon>,
  },
  {
    key: "risk:heat",
    label: "Risk",
    matches: ["risk", "risk:rules"],
    icon: <Icon><path d="M12 3.5 21 20H3z" /><path d="M12 10v4" /><path d="M12 17h.01" /></Icon>,
  },
];

export default function MobileBottomNav({
  active,
  onNav,
  onOpenMore,
  moreOpen = false,
}: {
  active: string;
  onNav: (key: string) => void;
  onOpenMore: () => void;
  moreOpen?: boolean;
}) {
  const isActive = (item: BottomNavItem) =>
    active === item.key || (item.matches?.includes(active) ?? false);

  return (
    <nav className="mobile-bottom-nav" aria-label="Primary">
      {BOTTOM_NAV_ITEMS.map((item) => {
        const on = isActive(item);
        return (
          <button
            key={item.key}
            type="button"
            className={`mobile-bottom-nav__tab${on ? " is-active" : ""}`}
            aria-current={on ? "page" : undefined}
            aria-label={item.label}
            onClick={() => onNav(item.key)}
          >
            {item.icon}
            <span className="mobile-bottom-nav__label">{item.label}</span>
          </button>
        );
      })}
      <button
        type="button"
        className={`mobile-bottom-nav__tab${moreOpen ? " is-active" : ""}`}
        aria-label="More"
        aria-expanded={moreOpen}
        onClick={onOpenMore}
      >
        <Icon><path d="M4 7h16" /><path d="M4 12h16" /><path d="M4 17h16" /></Icon>
        <span className="mobile-bottom-nav__label">More</span>
      </button>
    </nav>
  );
}
