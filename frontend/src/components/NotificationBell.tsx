/**
 * Notification Center bell — header dropdown of in-app notifications.
 *
 * Polls the unread count and lists recent notifications. Notifications are
 * informational; nothing here executes a trade.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";

interface Notif {
  id: string; kind: string; symbol: string | null; title: string;
  body: string; severity: "info" | "warning" | "critical"; read: boolean; created_at: string;
}

const SEV_TONE: Record<string, string> = {
  info: "var(--ink-dim)", warning: "var(--amber)", critical: "var(--red)",
};

export default function NotificationBell() {
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notif[]>([]);

  const poll = () => {
    (api.getUnreadCount() as Promise<{ unread: number }>).then(d => setUnread(d.unread)).catch(() => {});
  };
  useEffect(() => { poll(); const t = setInterval(poll, 30000); return () => clearInterval(t); }, []);

  const openMenu = () => {
    setOpen(o => !o);
    if (!open) {
      (api.getNotifications() as Promise<{ notifications: Notif[] }>)
        .then(d => setItems(d.notifications || [])).catch(() => {});
    }
  };

  const markAll = () => {
    api.markAllNotificationsRead().then(() => { setUnread(0); setItems(i => i.map(n => ({ ...n, read: true }))); });
  };

  return (
    <div style={{ position: "relative" }}>
      <button aria-label="Notifications" title="Notifications" onClick={openMenu}
        style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--ink-dim)", position: "relative", padding: "4px 6px", display: "flex", alignItems: "center" }}>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 01-3.46 0" />
        </svg>
        {unread > 0 && (
          <span className="tnum" style={{
            position: "absolute", top: -2, right: -2, background: "var(--red)", color: "#fff",
            fontSize: 9, fontWeight: 600, borderRadius: 8, padding: "0 4px", minWidth: 14, textAlign: "center",
          }}>{unread > 99 ? "99+" : unread}</span>
        )}
      </button>
      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
          <div style={{
            position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 41, width: 320,
            maxHeight: 420, overflowY: "auto", background: "var(--bg-2)", border: "1px solid var(--line-dim)",
            borderRadius: 6, boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          }}>
            <div style={{ padding: "9px 12px", borderBottom: "1px solid var(--line-dim)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>Notifications</span>
              {items.some(n => !n.read) && (
                <button className="btn-t" style={{ fontSize: 11, padding: "3px 8px" }} onClick={markAll}>Mark all read</button>
              )}
            </div>
            {items.length === 0 ? (
              <div style={{ padding: 20, textAlign: "center", fontSize: 12, color: "var(--ink-faint)" }}>No notifications.</div>
            ) : items.map(n => (
              <div key={n.id} style={{ padding: "9px 12px", borderBottom: "1px solid var(--line-dim)", opacity: n.read ? 0.6 : 1 }}>
                <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: SEV_TONE[n.severity], flexShrink: 0, marginTop: 4 }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: "var(--ink)" }}>{n.title}</div>
                    {n.body && <div style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 2 }}>{n.body}</div>}
                    <div style={{ fontSize: 10, color: "var(--ink-faint)", marginTop: 2 }}>{new Date(n.created_at).toLocaleString()}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
