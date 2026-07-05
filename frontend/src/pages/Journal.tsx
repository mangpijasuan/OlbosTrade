import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import ModeAnalytics from "./ModeAnalytics";

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
  mfe: number | null;
  mae: number | null;
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
  n == null ? "—" : (n >= 0 ? "+" : "") + "$" + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const holdDays = (entry: string | null, exit: string | null) => {
  if (!entry) return null;
  const from = new Date(entry);
  const to   = exit ? new Date(exit) : new Date();
  return Math.floor((to.getTime() - from.getTime()) / 86400000);
};

const COLS = ["Symbol", "Status", "Strategy", "Entry", "Exit", "Hold", "Score", "MFE", "MAE", "Capture", "Rules", "P&L"];

function RulesBadge({ v }: { v: boolean | null }) {
  if (v == null) return <span style={{ color: "var(--amber)", border: "1px solid var(--amber)", borderRadius: 2, padding: "0 5px", fontSize: 11 }}>Add</span>;
  return v
    ? <span style={{ color: "var(--green)", border: "1px solid rgba(34,197,94,0.4)", borderRadius: 2, padding: "0 5px", fontSize: 11 }}>Yes</span>
    : <span style={{ color: "var(--red)", border: "1px solid rgba(239,68,68,0.4)", borderRadius: 2, padding: "0 5px", fontSize: 11 }}>No</span>;
}

function JournalRow({ e, expanded, onToggle, onEdit }: {
  e: Entry; expanded: boolean; onToggle: () => void; onEdit: () => void;
}) {
  const days = holdDays(e.entry_date, e.exit_date);
  const isOpen = e.pnl == null;
  const pnlColor = isOpen ? "var(--ink-dim)" : (e.pnl ?? 0) >= 0 ? "var(--green)" : "var(--red)";

  return (
    <>
      <tr onClick={onToggle} style={{ cursor: "pointer" }} aria-expanded={expanded}>
        <td style={{ fontFamily: "var(--mono)", fontWeight: 600, color: "var(--ink)" }}>
          <span style={{ color: "var(--ink-faint)", marginRight: 6, fontSize: 10 }}>{expanded ? "▾" : "▸"}</span>
          {e.underlying || "—"}
        </td>
        <td>
          <span style={{
            fontFamily: "var(--mono)", fontSize: 9, padding: "2px 7px",
            border: `1px solid ${isOpen ? "rgba(6,182,212,0.4)" : "rgba(34,197,94,0.3)"}`,
            color: isOpen ? "var(--cyan)" : "var(--green)",
          }}>
            {isOpen ? "OPEN" : "CLOSED"}
          </span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
            {e.strategy?.replace(/_/g, " ").toUpperCase() || "—"}
          </span>
        </div>
        <div style={{ textAlign: "right" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 16, fontWeight: 700, color: pnlColor }}>
            {isOpen ? "OPEN" : fmt(e.pnl)}
          </span>
        </div>
      </div>

      {/* Row 2: meta info */}
      <div style={{ display: "flex", gap: 20, marginBottom: 8, flexWrap: "wrap" }}>
        {[
          { label: "ENTRY", val: e.entry_date?.slice(0, 10) || "—" },
          { label: "EXIT",  val: e.exit_date?.slice(0, 10)  || "—" },
          { label: "HOLD",  val: days != null ? `${days}d` : "—" },
          { label: "SCORE", val: e.signal_score != null ? e.signal_score.toFixed(3) : "—" },
          { label: "CONF",  val: e.confidence_level != null ? `${e.confidence_level}/5` : "—" },
          { label: "MFE",   val: e.mfe != null ? fmt(e.mfe) : "—" },
          { label: "MAE",   val: e.mae != null ? fmt(e.mae) : "—" },
        ].map(item => (
          <div key={item.label} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--ink-faint)", letterSpacing: "0.08em" }}>
              {item.label}
            </span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
              {item.val}
            </span>
          </div>
        ))}

        {/* Rules followed */}
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--ink-faint)", letterSpacing: "0.08em" }}>RULES</span>
          {e.followed_rules == null ? (
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--amber)",
              border: "1px solid rgba(245,158,11,0.4)", padding: "0px 5px" }}>ADD</span>
          ) : e.followed_rules ? (
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--green)",
              border: "1px solid rgba(34,197,94,0.3)", padding: "0px 5px" }}>YES ✓</span>
          ) : (
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)",
              border: "1px solid rgba(239,68,68,0.3)", padding: "0px 5px" }}>NO ✗</span>
          )}
        </div>
      </div>

      {/* Row 3: context + notes */}
      {(e.market_context || e.post_trade_notes) && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
          {e.market_context && (
            <div style={{ flex: 1, minWidth: 180 }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--ink-faint)", letterSpacing: "0.08em", marginBottom: 3 }}>CONTEXT</div>
              <div style={{ fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.5 }}>{e.market_context}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12 }}>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {(e.tags || []).map(t => (
                  <span key={t} style={{
                    fontSize: 11, padding: "1px 7px", borderRadius: 3,
                    background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", color: "var(--accent)",
                  }}>{t}</span>
                ))}
              </div>
              <button className="btn-t" onClick={(ev) => { ev.stopPropagation(); onEdit(); }}>Edit notes</button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function Journal() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab]         = useState<"entries" | "analysis" | "mode">("entries");
  const [editing, setEditing] = useState<EditState | null>(null);
  const [saving, setSaving]   = useState(false);
  const [impact, setImpact]   = useState<any>(null);
  const [filter, setFilter]   = useState<"all" | "open" | "closed">("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [entryRes, impactRes]: any = await Promise.all([
        api.getJournalEntries(),
        api.getRuleBreachImpact(),
      ]);
      setEntries(entryRes.entries || []);
      setImpact(impactRes.impact || null);
    } catch { } finally { setLoading(false); }
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

  const filtered = entries.filter(e => {
    if (filter === "open")   return e.pnl == null;
    if (filter === "closed") return e.pnl != null;
    return true;
  });

  const totalPnl  = entries.filter(e => e.pnl != null).reduce((s, e) => s + (e.pnl ?? 0), 0);
  const wins      = entries.filter(e => (e.pnl ?? 0) > 0).length;
  const closed    = entries.filter(e => e.pnl != null).length;
  const winRate   = closed > 0 ? Math.round(wins / closed * 100) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* Toolbar */}
      <div style={{
        padding: "6px 14px", borderBottom: "1px solid var(--line-dim)",
        background: "var(--bg-2)", display: "flex", alignItems: "center", gap: 8,
      }}>
        {([["entries", "Entries"], ["analysis", "Analysis"], ["mode", "Risk Profile"]] as const).map(([t, label]) => (
          <button key={t} className={`btn-t ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}>{label}</button>
        ))}
        <div style={{ width: 1, height: 16, background: "var(--line-dim)", margin: "0 4px" }} />
        {tab === "entries" && (["all","open","closed"] as const).map(f => (
          <button key={f} className={`btn-t ${filter === f ? "active" : ""}`}
            style={{ textTransform: "capitalize" }} onClick={() => setFilter(f)}>
            {f}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        {closed > 0 && (
          <div style={{ display: "flex", gap: 16, fontSize: 12 }}>
            <span style={{ color: "var(--ink-dim)" }}>
              <span className="tnum">{closed}</span> closed ·{" "}
              <span className="tnum" style={{ color: totalPnl >= 0 ? "var(--green)" : "var(--red)" }}>{fmt(totalPnl)}</span>
            </span>
            <span className="tnum" style={{ color: winRate >= 50 ? "var(--green)" : "var(--amber)" }}>
              Win {winRate}%
            </span>
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>

        {/* ── Entries tab ── */}
        {tab === "entries" && (
          <div style={{ overflowX: "auto" }}>
            <table className="t-table">
              <thead>
                <tr>
                  {COLS.map((c, i) => (
                    <th key={c} style={{ textAlign: i >= 5 && c !== "Rules" ? "right" : c === "Rules" ? "center" : "left", whiteSpace: "nowrap" }}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!loading && filtered.map(e => (
                  <JournalRow
                    key={e.id}
                    e={e}
                    expanded={expandedId === e.id}
                    onToggle={() => setExpandedId(expandedId === e.id ? null : e.id)}
                    onEdit={() => openEdit(e)}
                  />
                ))}
              </tbody>
            </table>
            {/* Empty / loading states keep the header skeleton above visible. */}
            {loading ? (
              <div style={{ padding: 40, textAlign: "center", fontSize: 12, color: "var(--ink-dim)" }}>Loading…</div>
            ) : filtered.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center" }}>
                <div style={{ fontSize: 13, color: "var(--ink)", marginBottom: 6 }}>No journal entries yet</div>
                <div style={{ fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                  Entries are created automatically when a trade fills.<br/>
                  MFE and MAE track after a fill; capture appears after the trade closes.
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* ── Analysis tab ── */}
        {tab === "analysis" && (
          <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)", borderRadius: 6 }}>
              <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--line-dim)" }}>
                <span className="panel-title">Rule breach impact</span>
                <span style={{ fontSize: 11, color: "var(--ink-dim)", marginLeft: 12 }}>
                  Requires followed-rules set on trades
                </span>
              </div>
              {!impact ? (
                <div style={{ padding: 24, textAlign: "center", fontSize: 12, color: "var(--ink-dim)" }}>
                  Need 5+ trades with followed-rules data.<br/>
                  Expand any trade and mark whether you followed the rules.
                </div>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)" }}>
                  {[
                    { label: "Followed — avg P&L",    val: fmt(impact.followed_avg_pnl),               color: "var(--green)" },
                    { label: "Breached — avg P&L",    val: fmt(impact.breached_avg_pnl),               color: "var(--red)"   },
                    { label: "Followed — win rate",   val: `${(impact.followed_win_rate*100).toFixed(1)}%`, color: "var(--green)" },
                    { label: "Cost of breach/trade",  val: fmt(impact.pnl_delta),                      color: "var(--amber)" },
                  ].map((s, i) => (
                    <div key={s.label} style={{ padding: "14px 16px", borderRight: i < 3 ? "1px solid var(--line-dim)" : "none" }}>
                      <div className="kicker" style={{ marginBottom: 6 }}>{s.label}</div>
                      <div className="data-val" style={{ color: s.color }}>{s.val}</div>
                    </div>
                  ))}
                </div>
              )}
              {impact && (
                <div style={{ padding: "10px 14px", borderTop: "1px solid var(--line-dim)", fontSize: 12, color: "var(--ink-dim)" }}>
                  {impact.summary}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Risk profile analytics tab ── */}
        {tab === "mode" && <ModeAnalytics />}
      </div>

      {/* Edit modal */}
      {editing && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
        }}>
          <div style={{
            background: "var(--bg-2)", border: "1px solid var(--line-dim)", borderRadius: 8,
            maxWidth: 500, width: "100%", padding: 24,
          }}>
            <div className="panel-title" style={{ marginBottom: 18 }}>Add trade notes</div>

            <div style={{ marginBottom: 16 }}>
              <div className="kicker" style={{ marginBottom: 8 }}>Did you follow the rules?</div>
              <div style={{ display: "flex", gap: 8 }}>
                {[
                  { val: true,  label: "Yes — followed rules",  color: "var(--green)" },
                  { val: false, label: "No — broke a rule",     color: "var(--red)"   },
                  { val: null,  label: "Skip",                  color: "var(--ink-dim)" },
                ].map(o => (
                  <button key={String(o.val)}
                    className={`btn-t ${editing.followed_rules === o.val ? "active" : ""}`}
                    style={editing.followed_rules === o.val ? { borderColor: o.color, color: o.color } : {}}
                    onClick={() => setEditing({ ...editing, followed_rules: o.val })}>
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <div className="kicker" style={{ marginBottom: 8 }}>Post-trade notes</div>
              <textarea
                value={editing.post_trade_notes}
                onChange={e => setEditing({ ...editing, post_trade_notes: e.target.value })}
                placeholder="What went right or wrong? What would you do differently?"
                rows={4}
                style={{
                  width: "100%", background: "var(--bg-3)",
                  border: "1px solid var(--line-dim)", color: "var(--ink)",
                  fontFamily: "var(--sans)", fontSize: 13, padding: "8px 10px",
                  outline: "none", resize: "vertical", boxSizing: "border-box", borderRadius: 4,
                }}
              />
            </div>

            <div style={{ marginBottom: 24 }}>
              <div className="kicker" style={{ marginBottom: 8 }}>Tags (comma-separated)</div>
              <input
                value={editing.tags}
                onChange={e => setEditing({ ...editing, tags: e.target.value })}
                placeholder="e.g. good-entry, high-iv, early-exit"
                style={{
                  width: "100%", background: "var(--bg-3)",
                  border: "1px solid var(--line-dim)", color: "var(--ink)",
                  fontFamily: "var(--sans)", fontSize: 13, padding: "7px 10px",
                  outline: "none", boxSizing: "border-box", borderRadius: 4,
                }}
              />
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn-t" onClick={() => setEditing(null)} style={{ flex: 1 }}>Cancel</button>
              <button className="btn-t active" onClick={saveEdit} disabled={saving} style={{ flex: 2 }}>
                {saving ? "Saving…" : "Save notes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
