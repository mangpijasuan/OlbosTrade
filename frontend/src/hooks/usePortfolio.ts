import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";

/** Live portfolio, positions, Greeks, and trade history from paper-trade API. */
export function usePortfolio() {
  const [positions, setPositions]   = useState<any[]>([]);
  const [portfolio, setPortfolio]   = useState<any>(null);
  const [greeks, setGreeks]         = useState<any>(null);
  const [lastSignal, setLastSignal] = useState<any>(null);
  const [cycleLog, setCycleLog]     = useState<any[]>([]);
  const [loading, setLoading]       = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, port, g, hist] = await Promise.all([
        api.getPositions() as any,
        api.getPortfolio() as any,
        api.getGreeksSummary() as any,
        api.getTradeHistory() as any,
      ]);
      setPositions(p.positions ?? []);
      setPortfolio(port.portfolio ?? null);
      setGreeks(g);
      const trades: any[] = hist.trades ?? [];
      setCycleLog(trades);
      if (trades.length > 0) setLastSignal(trades[0]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { positions, portfolio, greeks, lastSignal, cycleLog, loading, refresh };
}
