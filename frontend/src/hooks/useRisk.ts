import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";

export function useRisk() {
  const [portfolioState, setPortfolioState]   = useState<any>(null);
  const [riskState, setRiskState]             = useState<any>(null);
  const [guardrailStatus, setGuardrailStatus] = useState<any>(null);
  const [killSwitch, setKillSwitch]           = useState<any>(null);
  const [greeks, setGreeks]                   = useState<any>(null);
  const [error, setError]                     = useState<string | null>(null);
  const [loading, setLoading]                 = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setError(null);
      const [p, g, k, gr] = await Promise.all([
        api.getPortfolioState() as any,
        api.getGuardrailStatus() as any,
        api.getKillSwitchStatus() as any,
        api.getGreeksSummary() as any,
      ]);
      setPortfolioState(p);
      setRiskState(p);
      setGuardrailStatus(g);
      setKillSwitch(k);
      setGreeks(gr);
    } catch (e: any) {
      setError(e.message || "Failed to refresh risk data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000); // re-poll every 15s
    return () => clearInterval(interval);
  }, [refresh]);

  return { portfolioState, riskState, guardrailStatus, killSwitch, greeks, error, loading, refresh };
}
