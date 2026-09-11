/**
 * Decides whether to show the terminal or the login screen.
 *
 * This is UX, not security. The server enforces auth on every route regardless
 * of what this component renders — if this gate were deleted tomorrow, an
 * unauthenticated browser would get a screen full of 401s, not data. Worth
 * stating plainly because a "route guard" is easy to mistake for a boundary.
 */

import React from "react";

import Login from "../pages/Login";
import { useAuth } from "./AuthContext";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { phase, retry } = useAuth();

  if (phase === "checking") return <Splash>Checking session…</Splash>;

  if (phase === "error") {
    return (
      <Splash>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
          <div style={{ color: "var(--amber)" }}>Can't reach the server.</div>
          <div style={{ fontSize: 11, color: "var(--ink-faint)", maxWidth: 300, textAlign: "center", lineHeight: 1.5 }}>
            Not signing you out — this machine cannot tell whether the session
            is still good, and guessing either way would be wrong.
          </div>
          <button type="button" onClick={retry} style={{
            height: 40, padding: "0 20px",
            borderRadius: "var(--radius-control)",
            border: "1px solid var(--line-dim)",
            background: "var(--bg-3)", color: "var(--ink)",
            fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.08em",
            textTransform: "uppercase", cursor: "pointer",
          }}>
            Retry
          </button>
        </div>
      </Splash>
    );
  }

  if (phase === "anonymous") return <Login />;

  // "disabled" renders the app with no identity chrome at all — the existing
  // single-operator install, untouched. "signed-in" renders the same app.
  return <>{children}</>;
}

function Splash({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: "100dvh", display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--bg)", color: "var(--ink-dim)",
      fontFamily: "var(--mono)", fontSize: 12, padding: 16,
    }}>
      {children}
    </div>
  );
}
