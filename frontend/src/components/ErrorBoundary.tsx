/**
 * ErrorBoundary — keeps one page's render error from blanking the whole
 * dashboard (which during live trading could hide positions / kill-switch
 * state). Resets when the active page changes.
 */
import React from "react";

interface Props {
  resetKey?: string;
  children: React.ReactNode;
}
interface State {
  error: Error | null;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("Panel render error:", error, info);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            margin: 24,
            padding: 20,
            border: "1px solid var(--red)",
            borderRadius: 6,
            background: "rgba(239,68,68,0.08)",
            fontFamily: "var(--mono)",
            color: "var(--ink)",
          }}
        >
          <div style={{ color: "var(--red)", fontWeight: 700, marginBottom: 8 }}>
            This panel failed to render
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 12 }}>
            {this.state.error.message}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              padding: "6px 12px",
              borderRadius: 4,
              cursor: "pointer",
              border: "1px solid var(--cyan)",
              background: "var(--cyan-dim)",
              color: "var(--cyan)",
            }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
