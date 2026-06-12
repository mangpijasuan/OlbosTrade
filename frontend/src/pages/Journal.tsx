/**
 * Journal page — auto-populated from trade_recorder.
 *
 * Every trade that fills automatically gets a JournalEntry with:
 *   ✅ Strategy, underlying, mode, signal score, IV rank, regime (auto)
 *   ✅ P&L, entry/exit date (auto, filled on close)
 *   ✅ Market context string (auto)
 *   ⬜ pre_trade_thesis    ← trader fills in
 *   ⬜ followed_rules       ← trader fills in (powers rule breach analytics)
 *   ⬜ post_trade_notes     ← trader fills in
 *   ⬜ tags, mistake_tags   ← trader fills in
 *
 * The human fields can be left empty — the analytics still work
 * from the mechanical data alone.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";

interface Entry {
  id: string;
  trade_id: string | null;
  strategy: string | null;
  underlying: string | null;
  pre_trade_thesis: string;
  confidence_level: number;
  market_context: string;
  post_trade_notes: string | null;
  followed_rules: boolean | null;
  exit_felt_right: boolean | null;
  tags: string[];
  loss_category: string | null;
  mistake_tags: string[];
  pnl: number | null;
  signal_score: number | null;
  entry_date: string | null;
  exit_date: string | null;
}

interface EditState {
  entry_id: string;
  followed_rules: boolean | null;
  post_trade_notes: string;
  tags: string;
}

const fmt = (n: number | null) =>
  n == null ? "—" : (n >= 0 ? "+" : "") + "$" + Math.abs(n).toFixed(0);

export default function Journal() {
  const [entries, setEntries]     = useState<Entry[]>([]);
  const [loading, setLoading]     = useState(true);
  const [tab, setTab]             = useState<"entries" | "analysis">("entries");
  const [editing, setEditing]     = useState<EditState | null>(null);
  const [saving, setSaving]       = useState(false);
  const [impact, setImpact]       = useState<any>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [entryRes, impactRes]: any = await Promise.all([
        api.getJournalEntries(),
        api.getRuleBreachImpact(),
      ]);
      setEntries(entryRes.entries || []);
      setImpact(impactRes.impact || null);
    } catch { /* handled below */ } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const openEdit = (e: Entry) => setEditing({
    entry_id: e.id,
    followed_rules: e.followed_rules,
    post_trade_notes: e.post_trade_notes || "",
    tags: (e.tags || []).join(", "),
  });

  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await (api as any).updateJournalEntry(editing.entry_id, {
        followed_rules: editing.followed_rules,
        post_trade_notes: editing.post_trade_notes || null,
        tags: editing.tags.split(",").map((t: string) => t.trim()).filter(Boolean),
      });
      setEditing(null);
      await load();
    } finally { setSaving(false); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* Toolbar */}
      <div style={{
        padding: "8px 16px", borderBottom: "1px solid var(--line-dim)",
        background: "var(--bg-2)", display: "flex", alignItems: "center", gap: 8,
      }}>
        {(["entries", "analysis"] as const).map(t => (
          <button key={t} className={`btn-t ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}>{t.toUpperCase()}</button>
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          AUTO-POPULATED · ADD NOTES AFTER EACH TRADE
        </span>
      </div>

      <div style={{ flex: 1, overflow: "auto" }}>

        {/* ── Entries tab ── */}
        {tab === "entries" && (
          loading ? (
            <div style={{ padding: 40, textAlign: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
              LOADING...
            </div>
          ) : entries.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cyan)", marginBottom: 8 }}>
                NO JOURNAL ENTRIES YET
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", lineHeight: 1.8 }}>
                Entries are created automatically when a trade fills.<br/>
                Run the signal cycle or wait for 09:35 ET.
              </div>
            </div>
          ) : (
            <table className="t-table">
              <thead>
                <tr>
                  {["Date","Strategy","Mode","Score","P&L","Rules","Context","Notes"].map(h => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} onClick={() => openEdit(e)}
                    style={{ cursor: "pointer" }}>
                    <td className="mono" style={{ color: "var(--ink-dim)", whiteSpace: "nowrap" }}>
                      {e.entry_date || "—"}
                    </td>
                    <td className="mono" style={{ color: "var(--cyan)" }}>
                      {e.strategy || "—"}
                    </td>
                    <td>
                      {e.tags.find(t => ["conservative","balanced","aggressive","scalper"].includes(t)) && (
                        <span className={`mode-badge ${e.tags.find(t => ["conservative","balanced","aggressive","scalper"].includes(t))}`}>
                          {e.tags.find(t => ["conservative","balanced","aggressive","scalper"].includes(t))}
                        </span>
                      )}
                    </td>
                    <td className="mono">{e.signal_score?.toFixed(3) || "—"}</td>
                    <td className="mono" style={{ color: e.pnl == null ? "var(--ink-faint)" : e.pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                      {e.pnl == null ? "OPEN" : fmt(e.pnl)}
                    </td>
                    <td>
                      {e.followed_rules == null ? (
                        <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--amber)",
                          border: "1px solid rgba(245,158,11,0.4)", padding: "1px 6px" }}>
                          ADD
                        </span>
                      ) : e.followed_rules ? (
                        <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--green)",
                          border: "1px solid rgba(34,197,94,0.3)", padding: "1px 6px" }}>
                          YES
                        </span>
                      ) : (
                        <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--red)",
                          border: "1px solid rgba(239,68,68,0.3)", padding: "1px 6px" }}>
                          NO
                        </span>
                      )}
                    </td>
                    <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap", fontSize: 11, color: "var(--ink-dim)" }}>
                      {e.market_context || "—"}
                    </td>
                    <td style={{ fontSize: 11, color: "var(--ink-faint)" }}>
                      {e.post_trade_notes
                        ? <span style={{ color: "var(--ink)" }}>{e.post_trade_notes.slice(0, 40)}…</span>
                        : <span style={{ color: "var(--ink-faint)", fontStyle: "italic" }}>click to add</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}

        {/* ── Analysis tab ── */}
        {tab === "analysis" && (
          <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Rule breach impact */}
            <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)" }}>
              <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
                <span className="panel-title">Rule Breach Impact</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", marginLeft: 12 }}>
                  Requires followed_rules set on trades
                </span>
              </div>
              {!impact ? (
                <div style={{ padding: 24, textAlign: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
                  Need 5+ trades with followed_rules data.<br/>
                  Click any trade row and mark whether you followed the rules.
                </div>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)" }}>
                  {[
                    { label: "Followed — Avg P&L", val: fmt(impact.followed_avg_pnl), color: "var(--green)" },
                    { label: "Breached — Avg P&L", val: fmt(impact.breached_avg_pnl), color: "var(--red)" },
                    { label: "Followed — Win Rate", val: `${(impact.followed_win_rate*100).toFixed(1)}%`, color: "var(--green)" },
                    { label: "Cost of Breach/Trade", val: fmt(impact.pnl_delta), color: "var(--amber)" },
                  ].map((s, i) => (
                    <div key={s.label} style={{ padding: "16px 18px", borderRight: i < 3 ? "1px solid var(--line-dim)" : "none" }}>
                      <div className="kicker" style={{ marginBottom: 6 }}>{s.label}</div>
                      <div className="data-val" style={{ color: s.color }}>{s.val}</div>
                    </div>
                  ))}
                </div>
              )}
              {impact && (
                <div style={{ padding: "10px 14px", borderTop: "1px solid var(--line-dim)",
                  fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                  {impact.summary}
                </div>
              )}
            </div>

          </div>
        )}
      </div>

      {/* Edit modal */}
      {editing && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
        }}>
          <div style={{
            background: "var(--bg-2)", border: "1px solid var(--line-dim)",
            maxWidth: 480, width: "100%", padding: 24,
          }}>
            <div className="panel-title" style={{ marginBottom: 16 }}>
              ADD TRADE NOTES
            </div>

            {/* followed_rules */}
            <div style={{ marginBottom: 14 }}>
              <div className="kicker" style={{ marginBottom: 8 }}>Did you follow the rules?</div>
              <div style={{ display: "flex", gap: 8 }}>
                {[
                  { val: true,  label: "YES — followed rules" },
                  { val: false, label: "NO — broke a rule" },
                  { val: null,  label: "Skip" },
                ].map(o => (
                  <button key={String(o.val)} className={`btn-t ${editing.followed_rules === o.val ? "active" : ""}`}
                    onClick={() => setEditing({ ...editing, followed_rules: o.val })}>
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Post-trade notes */}
            <div style={{ marginBottom: 14 }}>
              <div className="kicker" style={{ marginBottom: 8 }}>Post-trade notes</div>
              <textarea
                value={editing.post_trade_notes}
                onChange={e => setEditing({ ...editing, post_trade_notes: e.target.value })}
                placeholder="What went right or wrong? What would you do differently?"
                rows={3}
                style={{
                  width: "100%", background: "var(--bg-3)",
                  border: "1px solid var(--line-dim)", color: "var(--ink)",
                  fontFamily: "var(--sans)", fontSize: 13, padding: "8px 10px",
                  outline: "none", resize: "vertical",
                }}
              />
            </div>

            {/* Tags */}
            <div style={{ marginBottom: 20 }}>
              <div className="kicker" style={{ marginBottom: 8 }}>Tags (comma-separated)</div>
              <input
                value={editing.tags}
                onChange={e => setEditing({ ...editing, tags: e.target.value })}
                placeholder="e.g. good-entry, high-iv, early-exit"
                style={{
                  width: "100%", background: "var(--bg-3)",
                  border: "1px solid var(--line-dim)", color: "var(--ink)",
                  fontFamily: "var(--mono)", fontSize: 12, padding: "7px 10px", outline: "none",
                }}
              />
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn-t" onClick={() => setEditing(null)} style={{ flex: 1 }}>
                CANCEL
              </button>
              <button className="btn-t active" onClick={saveEdit} disabled={saving}
                style={{ flex: 1 }}>
                {saving ? "SAVING..." : "SAVE NOTES"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
