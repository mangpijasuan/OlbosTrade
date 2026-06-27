/**
 * HoldToConfirmButton — intentional-friction button for destructive actions.
 *
 * The user must press and hold for `holdMs` (default 2.5s) while a progress bar
 * fills; releasing early cancels. This prevents a stray click from firing an
 * irreversible action (e.g. the kill switch flattening the whole book).
 */
import React, { useRef, useState, useCallback } from "react";

interface Props {
  label: string;
  confirmingLabel?: string;
  onConfirm: () => void;
  holdMs?: number;
  disabled?: boolean;
}

export default function HoldToConfirmButton({
  label,
  confirmingLabel = "HOLD…",
  onConfirm,
  holdMs = 2500,
  disabled = false,
}: Props) {
  const [progress, setProgress] = useState(0); // 0..1
  const [holding, setHolding] = useState(false);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number>(0);
  const firedRef = useRef(false);

  const stop = useCallback(() => {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    setHolding(false);
    setProgress(0);
  }, []);

  const tick = useCallback(() => {
    const elapsed = performance.now() - startRef.current;
    const p = Math.min(elapsed / holdMs, 1);
    setProgress(p);
    if (p >= 1) {
      if (!firedRef.current) {
        firedRef.current = true;
        onConfirm();
      }
      stop();
      return;
    }
    rafRef.current = requestAnimationFrame(tick);
  }, [holdMs, onConfirm, stop]);

  const start = useCallback(() => {
    if (disabled) return;
    firedRef.current = false;
    startRef.current = performance.now();
    setHolding(true);
    rafRef.current = requestAnimationFrame(tick);
  }, [disabled, tick]);

  return (
    <button
      className="btn-t danger"
      disabled={disabled}
      onMouseDown={start}
      onMouseUp={stop}
      onMouseLeave={stop}
      onTouchStart={start}
      onTouchEnd={stop}
      style={{
        position: "relative",
        overflow: "hidden",
        padding: "10px 0",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        userSelect: "none",
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {/* progress fill */}
      <span
        aria-hidden
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: `${progress * 100}%`,
          background: "rgba(239,68,68,0.35)",
          transition: holding ? "none" : "width 0.15s ease",
        }}
      />
      <span style={{ position: "relative", zIndex: 1 }}>
        {holding ? `${confirmingLabel} ${Math.round(progress * 100)}%` : label}
      </span>
    </button>
  );
}
