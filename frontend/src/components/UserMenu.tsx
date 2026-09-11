/**
 * Signed-in identity and sign-out, for the status bar.
 *
 * Renders nothing at all when auth is disabled — on a single-operator install
 * there is no identity to show, and an empty "account" affordance that does
 * nothing is worse than no affordance.
 */

import React, { useEffect, useRef, useState } from "react";

import { useAuthOptional } from "../auth/AuthContext";

export default function UserMenu() {
  // Optional on purpose: this is chrome inside TerminalLayout, and a missing
  // provider must mean "nothing to show", not a crash that takes the shell
  // down. See useAuthOptional.
  const auth = useAuthOptional();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!auth || auth.phase !== "signed-in" || !auth.user) return null;
  const { user, signOut, logoutWarning } = auth;

  // Local part only: the status bar is tight, and the domain is the same for
  // everyone on an instance.
  const shortName = user.email.split("@")[0];

  return (
    <div ref={wrapRef} style={{ position: "relative", display: "flex", alignItems: "center" }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account: ${user.email}`}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          height: 22, padding: "0 8px", borderRadius: 11,
          background: open ? "var(--bg-4)" : "transparent",
          border: "1px solid var(--line-dim)",
          color: "var(--ink-dim)", cursor: "pointer",
          fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em",
          maxWidth: 180,
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {shortName}
        </span>
        {user.tier !== "free" && (
          <span style={{ color: "var(--brand)", textTransform: "uppercase" }}>{user.tier}</span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          style={{
            position: "absolute", bottom: "calc(100% + 6px)", right: 0,
            minWidth: 220, maxWidth: "min(300px, calc(100vw - 32px))",
            background: "var(--bg-2)", border: "1px solid var(--line-dim)",
            borderRadius: "var(--radius-control)", boxShadow: "var(--raised-bezel)",
            padding: 10, zIndex: 60,
            display: "flex", flexDirection: "column", gap: 8,
          }}
        >
          <div style={{
            fontSize: 11, color: "var(--ink)", wordBreak: "break-all", lineHeight: 1.4,
          }}>
            {user.email}
          </div>
          <div style={{
            fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em",
            textTransform: "uppercase", color: "var(--ink-faint)",
          }}>
            {user.tier} tier
          </div>

          {logoutWarning && (
            <div style={{
              fontSize: 10, lineHeight: 1.4, color: "var(--amber)",
              border: "1px solid var(--amber)55", background: "var(--amber)14",
              borderRadius: 4, padding: "6px 8px",
            }}>
              {logoutWarning}
            </div>
          )}

          <button
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await signOut();
              } finally {
                setBusy(false);
                setOpen(false);
              }
            }}
            style={{
              height: 36, borderRadius: "var(--radius-control)",
              border: "1px solid var(--line-dim)", background: "var(--bg-3)",
              color: "var(--ink)", cursor: busy ? "progress" : "pointer",
              fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
          >
            {busy ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
