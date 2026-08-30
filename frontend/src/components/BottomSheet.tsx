/**
 * Bottom sheet for phones.
 *
 * The side drawer this replaces on mobile was `min(520px, 100vw)` wide, which
 * on a phone means a full-screen takeover that arrives from the right — a
 * gesture direction nothing on the device uses, with its only dismiss control
 * a Close button at the top, furthest from the thumb.
 *
 * A sheet instead: it rises from the bottom, stops short of the top so the
 * page behind stays visible as context, and can be dismissed three ways —
 * drag it down, tap the backdrop, or press Escape. Dragging is what makes it
 * feel native, so it is implemented rather than gestured at.
 *
 * Desktop keeps the side drawer. This is not a smaller version of that; it is
 * the shape the platform expects, and the two do not need to converge.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

/** Drag further than this and release, and the sheet closes. */
const DISMISS_THRESHOLD_PX = 96;
/** Never cover the whole screen — the page behind is the context. */
const MAX_HEIGHT = "86dvh";

export default function BottomSheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  labelledBy = "bottom-sheet-title",
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  labelledBy?: string;
}) {
  const [dragY, setDragY] = useState(0);
  const startY = useRef<number | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  // Escape closes, matching every other dismissible surface in the shell.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // The page behind must not scroll while the sheet is up, or dragging the
  // sheet scrolls the list underneath it instead.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  useEffect(() => { if (open) setDragY(0); }, [open]);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    // Only start a drag from the top of the content, otherwise a downward
    // swipe meant to scroll the sheet's own body would dismiss it instead.
    const el = sheetRef.current;
    if (el && el.scrollTop > 0) return;
    startY.current = e.touches[0].clientY;
  }, []);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (startY.current === null) return;
    const delta = e.touches[0].clientY - startY.current;
    // Downward only. Dragging up must not stretch the sheet past its top.
    setDragY(delta > 0 ? delta : 0);
  }, []);

  const onTouchEnd = useCallback(() => {
    if (startY.current === null) return;
    startY.current = null;
    setDragY((d) => {
      if (d > DISMISS_THRESHOLD_PX) onClose();
      return 0;
    });
  }, [onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      className="bottom-sheet-root"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 260,
        display: "flex",
        alignItems: "flex-end",
      }}
    >
      <div
        className="bottom-sheet-backdrop"
        onClick={onClose}
        // The backdrop is a dismiss affordance for pointer users; keyboard
        // users get Escape, so it needs no tab stop of its own.
        aria-hidden="true"
        style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.58)" }}
      />
      <div
        className="bottom-sheet glass-surface"
        style={{
          position: "relative",
          width: "100%",
          maxHeight: MAX_HEIGHT,
          display: "flex",
          flexDirection: "column",
          borderTop: "1px solid var(--line)",
          borderRadius: "14px 14px 0 0",
          boxShadow: "0 -20px 60px rgba(0,0,0,0.45)",
          transform: dragY ? `translateY(${dragY}px)` : undefined,
          // No transition mid-drag: the sheet must track the finger exactly.
          transition: dragY ? "none" : "transform 180ms ease-out",
          paddingBottom: "env(safe-area-inset-bottom, 0px)",
        }}
      >
        <div
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          style={{ flexShrink: 0, touchAction: "none", cursor: "grab" }}
        >
          {/* Grab handle — the affordance that says this thing moves. */}
          <div style={{ display: "flex", justifyContent: "center", padding: "8px 0 4px" }}>
            <div
              aria-hidden="true"
              style={{ width: 36, height: 4, borderRadius: 2, background: "var(--line)" }}
            />
          </div>
          <div
            className="panel-head"
            style={{ borderBottom: "1px solid var(--line-dim)", paddingBottom: 10 }}
          >
            <div style={{ minWidth: 0 }}>
              <div id={labelledBy} className="panel-title">{title}</div>
              {subtitle && <div className="kicker" style={{ marginTop: 4 }}>{subtitle}</div>}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              style={{
                flexShrink: 0,
                minWidth: 44,
                minHeight: 44,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                background: "none",
                border: "none",
                color: "var(--ink-dim)",
                fontSize: 20,
                lineHeight: 1,
                cursor: "pointer",
                touchAction: "manipulation",
              }}
            >
              ×
            </button>
          </div>
        </div>

        <div ref={sheetRef} style={{ overflowY: "auto", WebkitOverflowScrolling: "touch" }}>
          {children}
        </div>
      </div>
    </div>
  );
}
