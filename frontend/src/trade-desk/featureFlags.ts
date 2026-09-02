/**
 * Trade Desk 2.0 feature flags.
 * localStorage overrides take precedence; then Vite env; then defaults.
 * Rollback: set olbos.flags.trade_desk_v2 = "0" (or use Desk Settings toggle).
 */

export type TradeDeskFlag =
  | "trade_desk_v2"
  | "equity_desk_v2"
  | "options_desk_v2"
  | "copilot_queue_v2"
  | "execution_monitor_v2"
  | "trade_replay_v2"
  | "zero_dte_desk"
  | "options_flow"
  | "alpha_edge_integration"
  | "probabilistic_intelligence"
  | "mobile_trade_desk";

const STORAGE_PREFIX = "olbos.flags.";

/**
 * V2 desk suite default-on after paper gate.
 * Rollback: Desk Settings off, or localStorage olbos.flags.trade_desk_v2=0.
 * Experimental desks stay off.
 */
const DEFAULTS: Record<TradeDeskFlag, boolean> = {
  trade_desk_v2: true,
  equity_desk_v2: true,
  options_desk_v2: true,
  copilot_queue_v2: true,
  execution_monitor_v2: true,
  trade_replay_v2: true,
  zero_dte_desk: false,
  options_flow: false,
  alpha_edge_integration: false,
  probabilistic_intelligence: false,
  mobile_trade_desk: true,
};

const ENV_MAP: Partial<Record<TradeDeskFlag, string | undefined>> = {
  trade_desk_v2: import.meta.env.VITE_TRADE_DESK_V2 as string | undefined,
};

function parseBool(raw: string | null | undefined): boolean | null {
  if (raw == null || raw === "") return null;
  const v = raw.trim().toLowerCase();
  if (v === "1" || v === "true" || v === "on" || v === "yes") return true;
  if (v === "0" || v === "false" || v === "off" || v === "no") return false;
  return null;
}

export function isFlagEnabled(flag: TradeDeskFlag): boolean {
  try {
    const stored = parseBool(localStorage.getItem(STORAGE_PREFIX + flag));
    if (stored !== null) return stored;
  } catch {
    /* ignore */
  }
  const fromEnv = parseBool(ENV_MAP[flag]);
  if (fromEnv !== null) return fromEnv;
  return DEFAULTS[flag];
}

export function setFlagEnabled(flag: TradeDeskFlag, enabled: boolean): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + flag, enabled ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function isTradeDeskV2Enabled(): boolean {
  return isFlagEnabled("trade_desk_v2");
}
