/**
 * Sign-in screen.
 *
 * Deliberately plain. There is no "forgot password" (no reset flow exists yet
 * — Phase 4), no "create account" (invite-only, accounts come from
 * scripts/create_user.py), and no "remember me" (session length is an operator
 * setting, not a per-login choice). Offering any of them would be a link to
 * nowhere.
 */

import React, { useEffect, useRef, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { LoginError } from "../auth/authApi";

export default function Login() {
  const { signIn, expiredNotice } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => { emailRef.current?.focus(); }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(err instanceof LoginError ? err.message : "Could not reach the server.");
      // Clear the password but keep the email: the password is the part they
      // need to retype, and wiping both makes a typo cost twice as much.
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <div style={{
      minHeight: "100dvh",
      display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--bg)", color: "var(--ink)",
      fontFamily: "var(--sans)",
      padding: 16,                       // gutter survives at phone width
    }}>
      <form
        onSubmit={onSubmit}
        style={{
          width: "100%", maxWidth: 380,
          background: "var(--bg-2)",
          border: "1px solid var(--line-dim)",
          borderRadius: "var(--radius-card)",
          boxShadow: "var(--raised-bezel)",
          padding: 28,
          display: "flex", flexDirection: "column", gap: 18,
        }}
      >
        <header style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
          <img src="/favicon-32x32.png" alt="" width={40} height={40} />
          <span className="brand-wordmark" style={{
            fontSize: 20, letterSpacing: "0.14em", color: "var(--brand)", fontWeight: 700,
          }}>
            OLBOS
          </span>
          <span style={{
            fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink-faint)",
          }}>
            Operator sign-in
          </span>
        </header>

        {expiredNotice && (
          <div role="status" style={noticeStyle("var(--amber)")}>{expiredNotice}</div>
        )}

        <Field label="Email">
          <input
            ref={emailRef}
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            inputMode="email"
            required
            disabled={busy}
            style={inputStyle}
          />
        </Field>

        <Field label="Password">
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            disabled={busy}
            style={inputStyle}
          />
        </Field>

        {/* aria-live so a screen reader announces a failure that appears after
            submit, rather than leaving the user waiting on a silent form. */}
        <div aria-live="polite" style={{ minHeight: error ? undefined : 0 }}>
          {error && <div role="alert" style={noticeStyle("var(--red)")}>{error}</div>}
        </div>

        <button
          type="submit"
          disabled={busy || !email || !password}
          style={{
            height: 44,                  // >= 44px: a real tap target on phones
            borderRadius: "var(--radius-control)",
            border: "1px solid var(--line)",
            background: busy ? "var(--bg-3)" : "var(--fill-active)",
            color: busy ? "var(--ink-faint)" : "var(--ink)",
            fontFamily: "var(--mono)", fontSize: 12, letterSpacing: "0.08em",
            textTransform: "uppercase",
            cursor: busy ? "progress" : "pointer",
            opacity: !busy && (!email || !password) ? 0.55 : 1,
          }}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p style={{
          fontSize: 11, lineHeight: 1.5, color: "var(--ink-faint)",
          textAlign: "center", margin: 0,
        }}>
          Accounts are issued by the operator. There is no self-service signup.
        </p>
      </form>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{
        fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em",
        textTransform: "uppercase", color: "var(--ink-dim)",
      }}>
        {label}
      </span>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  height: 44,
  padding: "0 12px",
  borderRadius: "var(--radius-control)",
  border: "1px solid var(--line-dim)",
  background: "var(--bg-1)",
  color: "var(--ink)",
  // 16px: anything smaller makes iOS Safari zoom the page on focus, which on a
  // phone leaves the form half off-screen behind the keyboard.
  fontSize: 16,
  fontFamily: "var(--sans)",
  width: "100%",
};

function noticeStyle(tone: string): React.CSSProperties {
  return {
    padding: "9px 11px",
    borderRadius: "var(--radius-control)",
    border: `1px solid ${tone}55`,
    background: `${tone}14`,
    color: tone,
    fontSize: 12,
    lineHeight: 1.45,
  };
}
