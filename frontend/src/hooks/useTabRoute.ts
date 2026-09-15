/**
 * Keep a hub page's tab in the URL.
 *
 * The terminal's hub pages (Risk, Signals, Research, System, the legacy Trade
 * Desk) hold their active tab in local state and render it from an `initialTab`
 * prop. The registry in App.tsx gives most of those tabs their own page key —
 * `risk:heat` and `risk:rules` are both RiskCenter — so the URL is perfectly
 * capable of naming the tab. It just never heard about the change: clicking a
 * tab called setTab and nothing else, so the address bar still read
 * /terminal/risk/heat while you were looking at Guardrails.
 *
 * The consequence is the same one deep-linking was fixed for, one level down:
 * reload, bookmark, share and Back all restore the page but not the tab you
 * were actually on.
 *
 * This routes the change through the terminal nav instead, which updates the
 * URL, which re-renders the page with the new initialTab. The URL stays the
 * single source of truth rather than a second copy that drifts.
 *
 * A tab with no page key (the legacy desk's "Trading style" and "Manual Trade"
 * have none) still switches — it just does not change the URL. Silently
 * refusing to switch would be a worse trade than a URL that names the page but
 * not the tab.
 */

import { useEffect, useState } from "react";

import { useTerminalNav } from "../components/TerminalNavContext";

export function useTabRoute<T extends string>(
  initialTab: T,
  tabToPageKey: Readonly<Partial<Record<T, string>>>,
): [T, (next: T) => void] {
  const onNav = useTerminalNav();
  const [tab, setTab] = useState<T>(initialTab);

  // URL -> tab. Switching between two keys of the same hub swaps the registry
  // entry, so React usually remounts and useState picks the new value up on
  // its own; this covers the case where it re-renders instead of remounting,
  // so the two can never disagree.
  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  const changeTab = (next: T) => {
    // Set locally first so the tab responds even if the key is unmapped, and
    // so the UI does not wait on a navigation round trip.
    setTab(next);

    // Two guards, and either one alone is enough — mutation testing was how I
    // found that out. tabToPageKey is a plain object literal, so
    // `tabToPageKey["constructor"]` is a function rather than undefined, and an
    // unguarded `if (key) onNav(key)` would hand that function to the router.
    // hasOwnProperty rules it out at the lookup; the string test rules it out
    // at the call, because every inherited Object.prototype member is a
    // function or an object. Removing EITHER changes no behaviour; removing
    // both is caught by useTabRoute.test.tsx. Both stay: they are cheap, and
    // hasOwnProperty is how App.tsx states the same intent for the same reason.
    const key = Object.prototype.hasOwnProperty.call(tabToPageKey, next)
      ? tabToPageKey[next]
      : undefined;
    if (typeof key === "string" && key) onNav(key);
  };

  return [tab, changeTab];
}
