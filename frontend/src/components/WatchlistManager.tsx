/**
 * WatchlistManager — save, load, compare, and manage scan result watchlists.
 * Provides modal UI for watchlist operations (save, load, delete, compare).
 */

import React, { useState } from "react";
import { watchlistManager, Watchlist } from "../utils/watchlistManager";

interface WatchlistManagerProps {
  isOpen: boolean;
  onClose: () => void;
  currentCandidates: any[];
  assetType: "options" | "equity";
  onLoadWatchlist?: (candidates: any[]) => void;
}

export default function WatchlistManager({
  isOpen,
  onClose,
  currentCandidates,
  assetType,
  onLoadWatchlist,
}: WatchlistManagerProps) {
  const [watchlists, setWatchlists] = useState<Watchlist[]>(watchlistManager.list());
  const [saveName, setSaveName] = useState("");
  const [compareMode, setCompareMode] = useState(false);
  const [compareId1, setCompareId1] = useState<string>("");
  const [compareId2, setCompareId2] = useState<string>("");

  if (!isOpen) return null;

  const saveCurrentWatchlist = () => {
    if (!saveName.trim()) {
      alert("Please enter a watchlist name");
      return;
    }
    watchlistManager.save(saveName, currentCandidates, assetType);
    setWatchlists(watchlistManager.list());
    setSaveName("");
    alert(`Saved watchlist: ${saveName}`);
  };

  const loadWatchlist = (id: string) => {
    const wl = watchlistManager.load(id);
    if (wl && onLoadWatchlist) {
      onLoadWatchlist(wl.candidates);
      onClose();
    }
  };

  const deleteWatchlist = (id: string) => {
    if (window.confirm("Delete this watchlist?")) {
      watchlistManager.delete(id);
      setWatchlists(watchlistManager.list());
    }
  };

  const filteredWatchlists = watchlists.filter((w) => w.assetType === assetType);

  const comparisonResult =
    compareId1 && compareId2 ? watchlistManager.compare(compareId1, compareId2) : null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 998,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--bg)",
          border: "1px solid var(--line-dim)",
          borderRadius: 8,
          maxWidth: 800,
          maxHeight: "80vh",
          overflowY: "auto",
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--ink)" }}>
            Watchlist Manager
          </h2>
          <button
            onClick={onClose}
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--line-dim)",
              borderRadius: 4,
              width: 32,
              height: 32,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              fontSize: 16,
            }}
          >
            ✕
          </button>
        </div>

        {/* Tab selector */}
        <div style={{ display: "flex", gap: 8, borderBottom: "1px solid var(--line-dim)", paddingBottom: 12 }}>
          <button
            onClick={() => setCompareMode(false)}
            style={{
              background: !compareMode ? "var(--cyan)" : "var(--bg-2)",
              color: !compareMode ? "var(--bg)" : "var(--ink-dim)",
              border: "none",
              borderRadius: 4,
              padding: "6px 12px",
              fontFamily: "var(--mono)",
              fontSize: 11,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Save / Load
          </button>
          <button
            onClick={() => setCompareMode(true)}
            style={{
              background: compareMode ? "var(--cyan)" : "var(--bg-2)",
              color: compareMode ? "var(--bg)" : "var(--ink-dim)",
              border: "none",
              borderRadius: 4,
              padding: "6px 12px",
              fontFamily: "var(--mono)",
              fontSize: 11,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Compare
          </button>
        </div>

        {!compareMode ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Save section */}
            <div className="instrument-card" style={{ padding: 12 }}>
              <h3 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600 }}>
                Save Current Scan ({currentCandidates.length} candidates)
              </h3>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  type="text"
                  placeholder="Watchlist name (e.g., 'High EV Bull Puts')"
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  style={{
                    flex: 1,
                    background: "var(--bg-3)",
                    border: "1px solid var(--line-dim)",
                    borderRadius: 4,
                    padding: "6px 10px",
                    fontFamily: "var(--mono)",
                    fontSize: 11,
                    color: "var(--ink)",
                  }}
                />
                <button
                  onClick={saveCurrentWatchlist}
                  style={{
                    background: "var(--green)",
                    color: "var(--bg)",
                    border: "none",
                    borderRadius: 4,
                    padding: "6px 12px",
                    fontFamily: "var(--mono)",
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  SAVE
                </button>
              </div>
            </div>

            {/* Watchlists list */}
            <div>
              <h3 style={{ margin: "0 0 12px", fontSize: 13, fontWeight: 600 }}>
                Saved Watchlists ({filteredWatchlists.length})
              </h3>
              {filteredWatchlists.length === 0 ? (
                <div style={{ color: "var(--ink-faint)", fontSize: 12, padding: 12 }}>
                  No watchlists saved yet. Create one above.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {filteredWatchlists.map((wl) => (
                    <div
                      key={wl.id}
                      className="instrument-card"
                      style={{
                        padding: 10,
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", marginBottom: 4 }}>
                          {wl.name}
                        </div>
                        <div style={{ fontSize: 10, color: "var(--ink-dim)", display: "flex", gap: 12 }}>
                          <span>{wl.candidates.length} candidates</span>
                          <span>Avg EV: ${wl.scanMetrics.avgEV.toFixed(0)}</span>
                          <span>Avg Conf: {(wl.scanMetrics.avgConfidence * 100).toFixed(0)}%</span>
                          <span>
                            Saved: {new Date(wl.createdAt).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          onClick={() => loadWatchlist(wl.id)}
                          style={{
                            background: "var(--cyan)",
                            color: "var(--bg)",
                            border: "none",
                            borderRadius: 3,
                            padding: "4px 8px",
                            fontFamily: "var(--mono)",
                            fontSize: 10,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          LOAD
                        </button>
                        <button
                          onClick={() => deleteWatchlist(wl.id)}
                          style={{
                            background: "var(--bg-3)",
                            color: "var(--red)",
                            border: "1px solid var(--red)",
                            borderRadius: 3,
                            padding: "4px 8px",
                            fontFamily: "var(--mono)",
                            fontSize: 10,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          DELETE
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="instrument-card" style={{ padding: 12 }}>
              <h3 style={{ margin: "0 0 12px", fontSize: 13, fontWeight: 600 }}>
                Compare Two Watchlists
              </h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <select
                  value={compareId1}
                  onChange={(e) => setCompareId1(e.target.value)}
                  style={{
                    background: "var(--bg-3)",
                    border: "1px solid var(--line-dim)",
                    borderRadius: 4,
                    padding: "6px 8px",
                    fontSize: 11,
                    color: "var(--ink)",
                    cursor: "pointer",
                  }}
                >
                  <option value="">Select first watchlist...</option>
                  {filteredWatchlists.map((wl) => (
                    <option key={wl.id} value={wl.id}>
                      {wl.name} ({wl.candidates.length})
                    </option>
                  ))}
                </select>
                <select
                  value={compareId2}
                  onChange={(e) => setCompareId2(e.target.value)}
                  style={{
                    background: "var(--bg-3)",
                    border: "1px solid var(--line-dim)",
                    borderRadius: 4,
                    padding: "6px 8px",
                    fontSize: 11,
                    color: "var(--ink)",
                    cursor: "pointer",
                  }}
                >
                  <option value="">Select second watchlist...</option>
                  {filteredWatchlists.map((wl) => (
                    <option key={wl.id} value={wl.id}>
                      {wl.name} ({wl.candidates.length})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Comparison results */}
            {comparisonResult && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.3)", borderRadius: 4, padding: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--green)", marginBottom: 4 }}>
                    ✓ New Candidates ({comparisonResult.added.length})
                  </div>
                  {comparisonResult.added.length === 0 ? (
                    <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>None</div>
                  ) : (
                    <div style={{ fontSize: 11, color: "var(--ink-dim)", display: "flex", flexWrap: "wrap", gap: 8 }}>
                      {comparisonResult.added.map((c, i) => (
                        <span key={i} style={{ background: "var(--bg-2)", padding: "2px 6px", borderRadius: 2 }}>
                          {c.ticker}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 4, padding: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--red)", marginBottom: 4 }}>
                    ✗ Removed Candidates ({comparisonResult.removed.length})
                  </div>
                  {comparisonResult.removed.length === 0 ? (
                    <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>None</div>
                  ) : (
                    <div style={{ fontSize: 11, color: "var(--ink-dim)", display: "flex", flexWrap: "wrap", gap: 8 }}>
                      {comparisonResult.removed.map((c, i) => (
                        <span key={i} style={{ background: "var(--bg-2)", padding: "2px 6px", borderRadius: 2 }}>
                          {c.ticker}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div style={{ background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 4, padding: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--amber)", marginBottom: 4 }}>
                    ⟳ Changed Candidates ({comparisonResult.changed.length})
                  </div>
                  {comparisonResult.changed.length === 0 ? (
                    <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>None</div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {comparisonResult.changed.map((item, i) => (
                        <div key={i} style={{ fontSize: 10, background: "var(--bg-2)", padding: "6px 8px", borderRadius: 2 }}>
                          <div style={{ color: "var(--ink)", fontWeight: 600, marginBottom: 2 }}>
                            {item.before.ticker || item.after.ticker}
                          </div>
                          <div style={{ color: "var(--ink-dim)" }}>
                            EV: ${item.before.expected_value?.toFixed(0) || "?"} → ${item.after.expected_value?.toFixed(0) || "?"}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div style={{ display: "flex", gap: 8, paddingTop: 12, borderTop: "1px solid var(--line-dim)" }}>
          <button
            onClick={onClose}
            style={{
              flex: 1,
              background: "var(--bg-2)",
              border: "1px solid var(--line-dim)",
              borderRadius: 4,
              padding: "8px 12px",
              fontFamily: "var(--mono)",
              fontSize: 11,
              fontWeight: 600,
              cursor: "pointer",
              color: "var(--ink)",
            }}
          >
            CLOSE
          </button>
        </div>
      </div>
    </div>
  );
}
