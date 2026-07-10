/**
 * Watchlist manager — save/load/compare scan results.
 * Persists to localStorage (upgraded to IndexedDB when auth backend ready).
 */

export interface Watchlist {
  id: string;
  name: string;
  assetType: "options" | "equity";
  candidates: any[];
  createdAt: string;
  scanMetrics: {
    avgEV: number;
    avgConfidence: number;
    avgKelly: number;
    scanDate: string;
  };
}

const STORAGE_KEY = "olbos_watchlists";

export const watchlistManager = {
  /**
   * Get all saved watchlists from localStorage.
   */
  list(): Watchlist[] {
    try {
      const data = localStorage.getItem(STORAGE_KEY);
      return data ? JSON.parse(data) : [];
    } catch (e) {
      console.error("Failed to load watchlists:", e);
      return [];
    }
  },

  /**
   * Save current scan results as a named watchlist.
   */
  save(
    name: string,
    candidates: any[],
    assetType: "options" | "equity"
  ): Watchlist {
    const watchlist: Watchlist = {
      id: `wl_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      name: name.trim(),
      assetType,
      candidates,
      createdAt: new Date().toISOString(),
      scanMetrics: {
        avgEV: candidates.length > 0
          ? candidates.reduce((sum, c) => sum + c.expected_value, 0) / candidates.length
          : 0,
        avgConfidence: candidates.length > 0
          ? candidates.reduce((sum, c) => sum + c.confidence, 0) / candidates.length
          : 0,
        avgKelly: candidates.length > 0
          ? candidates.reduce((sum, c) => sum + c.kelly_fraction, 0) / candidates.length
          : 0,
        scanDate: new Date().toISOString(),
      },
    };

    const all = watchlistManager.list();
    all.push(watchlist);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
    return watchlist;
  },

  /**
   * Load a specific watchlist by ID.
   */
  load(id: string): Watchlist | null {
    const all = watchlistManager.list();
    return all.find((w) => w.id === id) || null;
  },

  /**
   * Delete a watchlist by ID.
   */
  delete(id: string): boolean {
    const all = watchlistManager.list();
    const filtered = all.filter((w) => w.id !== id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
    return filtered.length < all.length;
  },

  /**
   * Compare two watchlists — return added, removed, changed.
   */
  compare(
    id1: string,
    id2: string
  ): {
    added: any[];
    removed: any[];
    changed: Array<{ before: any; after: any }>;
  } {
    const w1 = watchlistManager.load(id1);
    const w2 = watchlistManager.load(id2);

    if (!w1 || !w2) {
      return { added: [], removed: [], changed: [] };
    }

    const map1 = new Map(w1.candidates.map((c) => [c.ticker, c]));
    const map2 = new Map(w2.candidates.map((c) => [c.ticker, c]));

    const added = Array.from(map2.values()).filter((c) => !map1.has(c.ticker));
    const removed = Array.from(map1.values()).filter((c) => !map2.has(c.ticker));
    const changed = Array.from(map2.values())
      .filter((c) => map1.has(c.ticker) && JSON.stringify(map1.get(c.ticker)) !== JSON.stringify(c))
      .map((after) => ({
        before: map1.get(after.ticker),
        after,
      }));

    return { added, removed, changed };
  },

  /**
   * Export watchlist as JSON.
   */
  exportJSON(id: string): string | null {
    const watchlist = watchlistManager.load(id);
    if (!watchlist) return null;
    return JSON.stringify(watchlist, null, 2);
  },

  /**
   * Import watchlist from JSON.
   */
  importJSON(json: string): Watchlist | null {
    try {
      const data = JSON.parse(json);
      const watchlist: Watchlist = {
        id: `wl_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        name: data.name || "Imported",
        assetType: data.assetType || "options",
        candidates: data.candidates || [],
        createdAt: new Date().toISOString(),
        scanMetrics: data.scanMetrics || {
          avgEV: 0,
          avgConfidence: 0,
          avgKelly: 0,
          scanDate: new Date().toISOString(),
        },
      };

      const all = watchlistManager.list();
      all.push(watchlist);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
      return watchlist;
    } catch (e) {
      console.error("Failed to import watchlist:", e);
      return null;
    }
  },
};
