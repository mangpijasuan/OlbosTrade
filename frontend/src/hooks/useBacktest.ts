import { useState } from "react";
import { api } from "../api/client";

const POLL_INTERVAL_MS = 1000;
const MAX_POLLS = 120;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

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
      let run = await api.runBacktest(params) as any;
      setResults(run);

      for (let i = 0; i < MAX_POLLS && ["queued", "running"].includes(run.status); i += 1) {
        await sleep(POLL_INTERVAL_MS);
        run = await api.getBacktestResults(run.run_id) as any;
        setResults(run);
      }

      if (["queued", "running"].includes(run.status)) {
        setError("Backtest is still running. Results will continue to be available in history.");
      } else if (run.status === "failed") {
        setError(run.error || "Backtest failed.");
      }
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadHistory = async () => {
    try { const h = await api.getBacktestHistory() as any; setHistory(h.runs ?? []); }
    catch (e: any) { setError(e.message); }
  };

  return { loading, results, history, error, runBacktest, loadHistory };
}
