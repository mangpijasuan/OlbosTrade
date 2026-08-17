/**
 * Shared types for signal attribution and risk-state display.
 *
 * `Availability<T>` replaces "safe defaults" for values that may not be
 * verifiable from the frontend's current data source. A missing or failed
 * fetch must render as `unavailable`/`unknown`, never fall back to a value
 * that could look like a normal-operation state (see CLAUDE task spec:
 * "never replace an unknown financial-risk state with a safe default").
 */
export type Availability<T> =
  | { status: "loading" }
  | { status: "available"; value: T; updatedAt?: string }
  | { status: "unavailable"; reason?: string }
  | { status: "error"; message?: string }
  | { status: "unknown" };

export type SignalDirection =
  | "BUY"
  | "SELL"
  | "HOLD"
  | "BULLISH"
  | "BEARISH"
  | "NEUTRAL"
  | string;

export type SignalAuthority = "execution" | "advisory" | "unknown";

/**
 * Normalized attribution for one directional signal. Every field besides
 * `direction` is optional/nullable on purpose — the component renders an
 * explicit "unknown"/"unavailable" state per field rather than omitting it,
 * so missing attribution is never silently hidden.
 */
export interface SignalAttributionData {
  direction: SignalDirection;
  /** Which system/engine produced it, e.g. "Equity Signal Engine", "Options Scan". */
  source?: string | null;
  /** e.g. "Daily", "Weekly", "4H", "DTE 30-45". */
  timeframe?: string | null;
  /** 0-1 confidence, when the source provides one. */
  confidence?: number | null;
  /** ISO timestamp the signal was generated/last updated. */
  updatedAt?: string | null;
  /** Whether this signal can currently reach execution, is advisory-only, or is not verifiable from the frontend. */
  authority?: SignalAuthority;
  /** Explicit stale override; if absent, staleness is inferred from updatedAt + staleAfterMs. */
  stale?: boolean;
  /** Freshness threshold in ms; default 15 minutes. */
  staleAfterMs?: number;
  /**
   * SHAP feature attribution from the AI scorer, when the source signal was
   * scored by one (options signals only — equity's rule-based scorer has no
   * model to explain). Absent/undefined means "not applicable for this
   * signal type," not "unknown" — the component renders nothing for it
   * rather than an explicit unavailable row, matching how stale/staleAfterMs
   * are treated as optional enrichment rather than core attribution.
   */
  topPositiveFactors?: { feature: string; value?: number; impact: number }[] | null;
  topNegativeFactors?: { feature: string; value?: number; impact: number }[] | null;
}
