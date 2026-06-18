import { useState } from "react";
import { api } from "../api/client";

// The backtest runs as a background job: POST /run returns a run_id with
// status "queued", and the real metrics only appear once GET /{id}/results
// reports status "completed". The hook must poll for completion and map the
// backend's *_pct field names onto the names the UI renders.
function normalizeResults(run: any) {
  return {
    ...run,
    total_return: run.total_return_pct ?? run.total_return ?? 0,
    max_drawdown: run.max_drawdown_pct ?? run.max_drawdown ?? 0,
    sharpe_ratio: run.sharpe_ratio ?? 0,
    win_rate: run.win_rate ?? 0,
    profit_factor: run.profit_factor ?? 0,
    total_trades: run.total_trades ?? 0,
  };
}

export function useBacktest() {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const runBacktest = async (params: {
    strategy: string; start_date: string; end_date: string;
    starting_capital?: number; signal_score_override?: number; mode?: string;
  }) => {
    setLoading(true); setError(null); setResults(null);
    try {
      const initial = await api.runBacktest(params) as any;
      const runId = initial.run_id;
      if (!runId) throw new Error("Backtest did not return a run_id");

      // Poll until the background run completes, fails, or we give up.
      const MAX_ATTEMPTS = 60;   // ~60s at 1s intervals
      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        const run = await api.getBacktestResults(runId) as any;
        if (run.status === "completed") {
          setResults(normalizeResults(run));
          return;
        }
        if (run.status === "failed") {
          throw new Error(run.error || "Backtest failed");
        }
        await new Promise(r => setTimeout(r, 1000));
      }
      throw new Error("Backtest timed out — still running after 60s");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async () => {
    try { const h = await api.getBacktestHistory() as any; setHistory(h.runs ?? []); }
    catch (e: any) { setError(e.message); }
  };

  return { loading, results, history, error, runBacktest, loadHistory };
}
