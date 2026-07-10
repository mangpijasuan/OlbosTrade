/**
 * useIbkrLiveControl — React hook for controlling IBKR live data (pause/resume)
 * Allows disconnecting from one device to login on another
 */

import { useCallback, useState, useEffect } from "react";

interface IBKRLiveStatus {
  is_paused: boolean;
  active_connections: number;
  subscriptions: number;
  subscription_keys: string[];
}

export function useIbkrLiveControl() {
  const [status, setStatus] = useState<IBKRLiveStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch current status
  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch("/api/ibkr/live/status");
      if (!response.ok) throw new Error("Failed to fetch status");
      const data = await response.json();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }, []);

  // Fetch status on mount
  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000); // Poll every 5 seconds
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // Pause live data
  const pause = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/ibkr/live/pause", { method: "POST" });
      if (!response.ok) throw new Error("Failed to pause");
      await fetchStatus();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to pause");
    } finally {
      setLoading(false);
    }
  }, [fetchStatus]);

  // Resume live data
  const resume = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/ibkr/live/resume", { method: "POST" });
      if (!response.ok) throw new Error("Failed to resume");
      await fetchStatus();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resume");
    } finally {
      setLoading(false);
    }
  }, [fetchStatus]);

  return {
    status,
    loading,
    error,
    pause,
    resume,
    isPaused: status?.is_paused ?? false,
    activeConnections: status?.active_connections ?? 0,
    subscriptionCount: status?.subscriptions ?? 0,
  };
}
