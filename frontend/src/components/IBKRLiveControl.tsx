/**
 * IBKRLiveControl — UI component for pausing/resuming IBKR live data
 * Allows logging in on other devices without conflicts
 */

import React, { useState } from "react";
import { useIbkrLiveControl } from "../hooks/useIbkrLiveControl";

interface IBKRLiveControlProps {
  compact?: boolean; // Show as small button vs full panel
}

export default function IBKRLiveControl({ compact = false }: IBKRLiveControlProps) {
  const { status, loading, error, pause, resume, isPaused, activeConnections } = useIbkrLiveControl();
  const [showTooltip, setShowTooltip] = useState(false);

  if (compact) {
    return (
      <div
        style={{
          position: "relative",
          display: "inline-block",
        }}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <button
          onClick={isPaused ? resume : pause}
          disabled={loading}
          style={{
            padding: "4px 8px",
            fontSize: 11,
            fontFamily: "var(--mono)",
            border: `1px solid ${isPaused ? "var(--red)" : "var(--green)"}`,
            background: "var(--bg-2)",
            color: isPaused ? "var(--red)" : "var(--green)",
            borderRadius: 3,
            cursor: loading ? "wait" : "pointer",
            opacity: loading ? 0.6 : 1,
            transition: "all 0.2s",
          }}
        >
          {loading ? "..." : isPaused ? "Resume" : "Pause"}
        </button>

        {showTooltip && (
          <div
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              marginTop: 4,
              padding: "6px 8px",
              background: "var(--bg-3)",
              border: "1px solid var(--ink-faint)",
              borderRadius: 3,
              fontSize: 10,
              whiteSpace: "nowrap",
              zIndex: 1000,
            }}
          >
            {isPaused ? "Resume live data" : "Pause to login on other devices"}
          </div>
        )}
      </div>
    );
  }

  // Full panel view
  return (
    <div
      className="instrument-card"
      style={{
        padding: "12px",
        border: "1px solid var(--ink-faint)",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div>
          <h3
            style={{
              margin: 0,
              fontSize: 12,
              fontWeight: 600,
              color: "var(--ink)",
            }}
          >
            IBKR Connection Control
          </h3>
          <div
            style={{
              fontSize: 10,
              color: "var(--ink-faint)",
              marginTop: 2,
            }}
          >
            Status: <strong>{isPaused ? "🔴 Paused" : "🟢 Active"}</strong>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            gap: 8,
          }}
        >
          <button
            onClick={pause}
            disabled={loading || isPaused}
            style={{
              padding: "6px 12px",
              fontSize: 11,
              fontFamily: "var(--mono)",
              border: "1px solid var(--red)",
              background: isPaused ? "var(--bg-3)" : "var(--red)",
              color: isPaused ? "var(--red)" : "white",
              borderRadius: 3,
              cursor: loading || isPaused ? "not-allowed" : "pointer",
              opacity: loading || isPaused ? 0.5 : 1,
              transition: "all 0.2s",
            }}
          >
            {loading ? "..." : "Pause"}
          </button>

          <button
            onClick={resume}
            disabled={loading || !isPaused}
            style={{
              padding: "6px 12px",
              fontSize: 11,
              fontFamily: "var(--mono)",
              border: "1px solid var(--green)",
              background: !isPaused ? "var(--bg-3)" : "var(--green)",
              color: !isPaused ? "var(--green)" : "white",
              borderRadius: 3,
              cursor: loading || !isPaused ? "not-allowed" : "pointer",
              opacity: loading || !isPaused ? 0.5 : 1,
              transition: "all 0.2s",
            }}
          >
            {loading ? "..." : "Resume"}
          </button>
        </div>
      </div>

      {status && (
        <div
          style={{
            fontSize: 10,
            color: "var(--ink-dim)",
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 8,
          }}
        >
          <div>
            <span style={{ color: "var(--ink-faint)" }}>Active Connections:</span> {status.active_connections}
          </div>
          <div>
            <span style={{ color: "var(--ink-faint)" }}>Subscriptions:</span> {status.subscriptions}
          </div>
        </div>
      )}

      {error && (
        <div
          style={{
            marginTop: 8,
            padding: "6px 8px",
            background: "var(--red)",
            color: "white",
            borderRadius: 3,
            fontSize: 10,
          }}
        >
          ⚠ {error}
        </div>
      )}

      <div
        style={{
          marginTop: 8,
          padding: "8px",
          background: "var(--bg-3)",
          borderRadius: 3,
          fontSize: 9,
          color: "var(--ink-faint)",
          lineHeight: "1.4",
        }}
      >
        <strong>💡 Usage:</strong> Click "Pause" to disconnect live data and login on another device. Click "Resume"
        when ready to receive updates again.
      </div>
    </div>
  );
}
