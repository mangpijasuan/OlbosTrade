import React from "react";

/**
 * Catches render-time exceptions in its children and shows the error on screen
 * instead of letting React unmount the whole tree (which produced a blank page).
 * Use it around pages and major panels so one bad component can't take down the
 * entire dashboard.
 */
interface Props { children: React.ReactNode; label?: string; }
interface State { error: Error | null; }

export default class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Surface to the console for debugging too.
    console.error("ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          margin: 12, padding: 16, border: "1px solid var(--red, #ef4444)",
          borderRadius: 6, background: "rgba(239,68,68,0.08)",
          fontFamily: "var(--mono, monospace)", fontSize: 12, color: "#eef2f7",
        }}>
          <div style={{ fontWeight: 700, color: "#ef4444", marginBottom: 8 }}>
            ⚠ {this.props.label || "This section"} failed to render
          </div>
          <div style={{ whiteSpace: "pre-wrap", color: "#f59e0b", marginBottom: 8 }}>
            {this.state.error.message}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              padding: "4px 12px", fontSize: 11, cursor: "pointer",
              background: "var(--bg-2, #11151c)", color: "#eef2f7",
              border: "1px solid var(--line-dim, #2a2f3a)", borderRadius: 4,
            }}
          >Retry</button>
        </div>
      );
    }
    return this.props.children;
  }
}
