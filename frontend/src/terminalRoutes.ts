/**
 * The URL <-> terminal-page mapping.
 *
 * Until this existed the terminal held its active page in React state and
 * never read the pathname, so EVERY /terminal/* URL rendered the Dashboard.
 * Reloading a page, bookmarking a view, sharing a link, or pressing the
 * browser's back button all landed on the Dashboard — and nothing said so,
 * because the URL in the bar still read /terminal/risk.
 *
 * Page keys are `group:sub` (`markets:chart`, `trade:overview`) or a bare word
 * (`dashboard`, `journal`). A colon is legal in a path segment but survives
 * copy-paste and server logs badly — it gets percent-encoded by some clients
 * and not others — so the colon becomes a slash on the way out and back:
 *
 *     markets:chart   <->   /terminal/markets/chart
 *     dashboard       <->   /terminal/dashboard
 *
 * Kept as a standalone module, free of React, so the mapping can be tested
 * directly rather than through a rendered router.
 */

export const TERMINAL_BASE = "/terminal";

/** Where a bare /terminal lands. Every marketing CTA links there. */
export const DEFAULT_PAGE = "dashboard";

/** `markets:chart` -> `markets/chart` */
export function pageKeyToPath(key: string): string {
  return key.trim().toLowerCase().split(":").filter(Boolean).join("/");
}

/** `markets:chart` -> `/terminal/markets/chart` */
export function pageKeyToUrl(key: string): string {
  const path = pageKeyToPath(key);
  return path ? `${TERMINAL_BASE}/${path}` : TERMINAL_BASE;
}

/**
 * `/terminal/markets/chart` -> `markets:chart`
 *
 * Accepts either a full pathname or the splat that react-router hands the
 * `/terminal/*` route, so callers do not have to care which they hold.
 * Anything empty resolves to DEFAULT_PAGE: a bare /terminal is the link every
 * CTA on the marketing page uses, and it must open the terminal, not an error.
 *
 * An unrecognised key is returned as-is rather than silently rewritten to the
 * dashboard. App renders UnknownPage for it and the URL stays put, so a typo
 * or a dead bookmark says so instead of quietly showing a different page —
 * which is the failure this module exists to remove.
 */
export function pathToPageKey(pathOrSplat: string | undefined | null): string {
  if (!pathOrSplat) return DEFAULT_PAGE;

  let raw = pathOrSplat.split("?")[0].split("#")[0];

  // DECODE BEFORE SPLITTING, not after. Splitting first leaves an encoded
  // separator trapped inside a segment: "/terminal/markets%2Fchart" became the
  // single key "markets/chart", which matches no page and rendered
  // UnknownPage. Clients that percent-encode "/" are the ones this module
  // claims to support, so they have to resolve to the same page as everyone
  // else. A malformed escape must not throw and take the terminal down, so
  // the decode falls back to the raw string.
  try {
    raw = decodeURIComponent(raw);
  } catch {
    /* not valid percent-encoding — use it as typed */
  }

  // Case-insensitively, and only on a path boundary. React Router matches
  // `/terminal/*` case-insensitively, so /TERMINAL/risk mounts the terminal;
  // a case-sensitive strip left "TERMINAL" in the key ("terminal:risk") and
  // rendered UnknownPage for a URL the router had already accepted. The
  // boundary check keeps a hypothetical /terminalish/... from being mangled.
  const lower = raw.toLowerCase();
  const base = TERMINAL_BASE.toLowerCase();
  if (lower === base || lower.startsWith(`${base}/`)) {
    raw = raw.slice(TERMINAL_BASE.length);
  }

  const segments = raw
    .split("/")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);

  return segments.length ? segments.join(":") : DEFAULT_PAGE;
}
