import { useState } from "react";
import { api } from "../api/client";

export function useBacktest() {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const runBacktest = async (params: {
    strategy: string; start_date: string; end_date: string;
    starting_capital?: number; signal_score_override?: number;
  }) => {
    setLoading(true); setError(null);
    try {
      const run = await api.runBacktest(params) as any;
      setResults(run);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadHistory = async () => {
    try { const h = await api.getBacktestHistory() as any; setHistory(h.runs ?? []); }
    catch (e: any) { setError(e.message); }
  };

  return { loading, results, history, error, runBacktest, loadHistory };
}
