/**
 * Positions + latest scan candidates for the Alpha Edge panel.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AssetTab } from "../pages/EquitySignals";
import {
  buildAlphaEdgeCandidates,
  type AlphaEdgeCandidate,
  type EquitySignalRow,
  type OptionsSignalRow,
  type PositionRow,
} from "../utils/alphaEdgeCandidates";

export function useAlphaEdgeWatchlist(assetTab: AssetTab) {
  const [candidates, setCandidates] = useState<AlphaEdgeCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const assetType: "equity" | "options" = assetTab === "equities" ? "equity" : "options";

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [posRes, sigRes] = await Promise.all([
        api.getPositions() as Promise<{ positions?: PositionRow[] }>,
        assetType === "equity"
          ? (api.getEquitySignals(150) as Promise<{ signals?: EquitySignalRow[] }>)
          : (api.getOptionsSignals(80) as Promise<{ signals?: OptionsSignalRow[] }>),
      ]);
      const positions = posRes.positions || [];
      const signals = sigRes.signals || [];
      setCandidates(buildAlphaEdgeCandidates(positions, signals, assetType));
      setLastRefresh(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setCandidates([]);
    } finally {
      setLoading(false);
    }
  }, [assetType]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 60000);
    return () => clearInterval(id);
  }, [refresh]);

  return { candidates, loading, error, refresh, lastRefresh, assetType };
}
