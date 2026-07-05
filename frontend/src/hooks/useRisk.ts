import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";

export function useRisk() {
  const [portfolioState, setPortfolioState]   = useState<any>(null);
  const [riskState, setRiskState]             = useState<any>(null);
  const [guardrailStatus, setGuardrailStatus] = useState<any>(null);
  const [reconciliation, setReconciliation]   = useState<any>(null);
  const [killSwitch, setKillSwitch]           = useState<any>(null);
  const [loading, setLoading]                 = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, g, r, k] = await Promise.all([
        (api.getPortfolioState() as any).catch(() => null),
        (api.getGuardrailStatus() as any).catch(() => null),
        (api.getLatestReconciliation() as any).catch(() => null),
        (api.getKillSwitchStatus() as any).catch(() => null),
      ]);
      setPortfolioState(p);
      setRiskState(p);        // riskState mirrors portfolioState
      setGuardrailStatus(g);
      setReconciliation(r?.snapshot ?? null);
      setKillSwitch(k);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000); // re-poll every 15s
    return () => clearInterval(interval);
  }, [refresh]);

  return { portfolioState, riskState, guardrailStatus, reconciliation, killSwitch, loading, refresh };
}
