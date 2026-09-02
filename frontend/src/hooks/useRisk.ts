import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";

export function useRisk() {
  const [portfolioState, setPortfolioState]   = useState<any>(null);
  const [riskState, setRiskState]             = useState<any>(null);
  const [guardrailStatus, setGuardrailStatus] = useState<any>(null);
  const [reconciliation, setReconciliation]   = useState<any>(null);
  const [killSwitch, setKillSwitch]           = useState<any>(null);
  const [loading, setLoading]                 = useState(false);
  // Distinguishes "portfolio state genuinely failed to fetch" from "not yet
  // loaded" — swallowing the error into `null` made both look identical,
  // which is how account/portfolio value ended up falling back to a
  // fabricated default instead of an explicit unavailable state.
  const [portfolioStateError, setPortfolioStateError] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      let portfolioStateFailed = false;
      const [p, g, r, k] = await Promise.all([
        (api.getPortfolioState() as any).catch(() => { portfolioStateFailed = true; return null; }),
        (api.getGuardrailStatus() as any).catch(() => null),
        (api.getLatestReconciliation() as any).catch(() => null),
        (api.getKillSwitchStatus() as any).catch(() => null),
      ]);
      setPortfolioState(p);
      setRiskState(p);        // riskState mirrors portfolioState
      setPortfolioStateError(portfolioStateFailed);
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

  return { portfolioState, riskState, portfolioStateError, guardrailStatus, reconciliation, killSwitch, loading, refresh };
}
