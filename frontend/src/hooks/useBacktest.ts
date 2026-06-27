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
    setLoading(true); setError(null); setResults(null);
    try {
      // /run is async — it returns {run_id, status:"queued"}. Poll the results
      // endpoint until the backtest completes or fails (don't render the queued
      // stub as if it had metrics).
      const run = await api.runBacktest(params) as any;
      const runId = run?.run_id;
      if (!runId) { setResults(run); return; }
      setResults(run); // show queued/running state

      const deadline = Date.now() + 180_000; // 3-min cap
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 1500));
        const res = await api.getBacktestResults(runId) as any;
        setResults(res);
        if (res?.status === "completed") return;
        if (res?.status === "failed") { setError(res.error || "Backtest failed"); return; }
      }
      setError("Backtest timed out — check server logs.");
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadHistory = async () => {
    try { const h = await api.getBacktestHistory() as any; setHistory(h.runs ?? []); }
    catch (e: any) { setError(e.message); }
  };

  return { loading, results, history, error, runBacktest, loadHistory };
}
