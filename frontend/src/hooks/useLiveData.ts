/**
 * useLiveData — React hook for IBKR live data subscriptions.
 * Manages WebSocket connection and candidate updates.
 */

import { useEffect, useState, useRef } from "react";
import { ibkrLiveData, ChainUpdate } from "../services/ibkrLiveData";

interface UseLiveDataOptions {
  enabled?: boolean;
  updateInterval?: number; // ms between batched updates
}

export function useLiveData(candidates: any[], options: UseLiveDataOptions = {}) {
  const { enabled = true, updateInterval = 2000 } = options;

  const [liveData, setLiveData] = useState<Map<string, ChainUpdate>>(new Map());
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const unsubscribeRefs = useRef<Array<() => void>>([]);
  const updateQueueRef = useRef<Map<string, ChainUpdate>>(new Map());
  const batchTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Initialize connection on mount
  useEffect(() => {
    if (!enabled) return;

    ibkrLiveData.connect().then((connected) => {
      setIsConnected(connected);
      if (connected) {
        subscribeToCandidates();
      }
    });

    return () => {
      unsubscribeRefs.current.forEach((unsub) => unsub());
      if (batchTimerRef.current) clearInterval(batchTimerRef.current);
    };
  }, [enabled]);

  // Subscribe to candidate updates
  const subscribeToCandidates = () => {
    if (!isConnected) return;

    // For options: subscribe to each spread
    candidates.forEach((c) => {
      if (c.short_strike && c.long_strike) {
        const key = `${c.ticker}:${c.short_strike}:${c.long_strike}:${c.option_type}`;
        const unsub = ibkrLiveData.subscribe(key, (data) => {
          // Batch updates to avoid excessive re-renders
          updateQueueRef.current.set(key, data as ChainUpdate);
        });
        unsubscribeRefs.current.push(unsub);
      }
      // For equity: subscribe to ticker
      else {
        const key = c.ticker;
        const unsub = ibkrLiveData.subscribe(key, (data) => {
          updateQueueRef.current.set(key, data as ChainUpdate);
        });
        unsubscribeRefs.current.push(unsub);
      }
    });

    // Batch update interval
    if (batchTimerRef.current) clearInterval(batchTimerRef.current);
    batchTimerRef.current = setInterval(() => {
      if (updateQueueRef.current.size > 0) {
        setLiveData((prev) => {
          const next = new Map(prev);
          updateQueueRef.current.forEach((v, k) => {
            next.set(k, v);
          });
          updateQueueRef.current.clear();
          return next;
        });
        setLastUpdate(new Date());
      }
    }, updateInterval);
  };

  // Re-subscribe when candidates change
  useEffect(() => {
    if (!isConnected) return;

    unsubscribeRefs.current.forEach((unsub) => unsub());
    unsubscribeRefs.current = [];
    subscribeToCandidates();
  }, [candidates, isConnected]);

  /**
   * Get live data for a candidate, or fallback to cached value.
   */
  const getUpdatedCandidate = (candidate: any): any => {
    const key = candidate.short_strike
      ? `${candidate.ticker}:${candidate.short_strike}:${candidate.long_strike}:${candidate.option_type}`
      : candidate.ticker;

    const update = liveData.get(key);
    if (!update) return candidate;

    return {
      ...candidate,
      credit: update.credit ?? candidate.credit,
      short_delta: update.delta ?? candidate.short_delta,
      iv_rank: update.iv ?? candidate.iv_rank,
      last_update: update.timestamp,
    };
  };

  return {
    isConnected,
    lastUpdate,
    liveData,
    getUpdatedCandidate,
  };
}
