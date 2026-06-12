import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";

export function useRisk() {
  const [portfolioState, setPortfolioState]   = useState<any>(null);
  const [riskState, setRiskState]             = useState<any>(null);
  const [guardrailStatus, setGuardrailStatus] = useState<any>(null);
  const [killSwitch, setKillSwitch]           = useState<any>(null);
  const [loading, setLoading]                 = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, g, k] = await Promise.all([
        api.getPortfolioState() as any,
        api.getGuardrailStatus() as any,
        api.getKillSwitchStatus() as any,
      ]);
      setPortfolioState(p);
      setRiskState(p);        // riskState mirrors portfolioState
      setGuardrailStatus(g);
      setKillSwitch(k);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { portfolioState, riskState, guardrailStatus, killSwitch, loading, refresh };
}
