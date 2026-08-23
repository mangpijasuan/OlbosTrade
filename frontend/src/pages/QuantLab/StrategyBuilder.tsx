/**
 * QuantLab/StrategyBuilder — visual strategy builder page.
 *
 * Users compose a strategy from ENTRY / FILTER / CONFIRMATION / REGIME / RISK /
 * EXIT / EXECUTION layers using the BlockBuilder component, then save it to the
 * backend as a versioned, deterministic JSON document.
 */

import React, { useState } from "react";
import { Panel, Button } from "../../components/ui";
import BlockBuilder, { ConditionBlockDef } from "../../components/QuantLab/BlockBuilder";
import { api } from "../../api/client";

const REGIMES = ["ANY", "LOW_VOL_TRENDING", "NORMAL_MEAN_REVERT", "HIGH_VOL_TRENDING", "CRISIS"];
const DIRECTIONS = ["LONG", "SHORT", "BOTH"];

const inp: React.CSSProperties = {
  width: "100%", background: "var(--bg-3)", border: "1px solid var(--line-dim)",
  color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
  padding: "7px 10px", outline: "none", boxSizing: "border-box",
};

const sel: React.CSSProperties = { ...inp };

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div style={{ marginBottom: 12 }}>
    <div className="kicker" style={{ marginBottom: 5 }}>{label}</div>
    {children}
  </div>
);

interface Form {
  name: string;
  description: string;
  direction: string;
  entry: ConditionBlockDef[];
  entry_logic: string;
  filter: ConditionBlockDef[];
  filter_logic: string;
  confirmation: ConditionBlockDef[];
  confirmation_logic: string;
  regime: string;
  stop_atr_mult: number;
  target_atr_mult: number;
  position_size_pct: number;
  exit: ConditionBlockDef[];
  exit_logic: string;
  max_concurrent_positions: number;
  commission_per_share: number;
  spread_pct: number;
  slippage_pct: number;
  max_daily_loss_pct: number;
  max_drawdown_pct: number;
}

const DEFAULT_FORM: Form = {
  name: "",
  description: "",
  direction: "LONG",
  entry: [{ indicator: "EMA", period: 20, operator: "crosses_above", compare_to: "EMA", compare_period: 50, value: 0 }],
  entry_logic: "AND",
  filter: [{ indicator: "ADX", period: 14, operator: ">", compare_to: "VALUE", compare_period: 0, value: 25 }],
  filter_logic: "AND",
  confirmation: [],
  confirmation_logic: "AND",
  regime: "ANY",
  stop_atr_mult: 1.5,
  target_atr_mult: 3.0,
  position_size_pct: 2.0,
  exit: [],
  exit_logic: "OR",
  max_concurrent_positions: 5,
  commission_per_share: 0.005,
  spread_pct: 0.001,
  slippage_pct: 0.001,
  max_daily_loss_pct: 3.0,
  max_drawdown_pct: 15.0,
};

export default function StrategyBuilderPage() {
  const [form, setForm] = useState<Form>(DEFAULT_FORM);
  const [saving, setSaving]   = useState(false);
  const [result, setResult]   = useState<{ id: string; version: number } | null>(null);
  const [error, setError]     = useState<string | null>(null);

  const set = (patch: Partial<Form>) => setForm(f => ({ ...f, ...patch }));

  const handleSave = async () => {
    if (!form.name.trim()) { setError("Strategy name is required"); return; }
    if (!form.entry.length) { setError("At least one entry condition is required"); return; }
    setSaving(true); setError(null); setResult(null);
    try {
      const res: any = await api.createQuantStrategy(form);
      setResult({ id: res.strategy_id, version: res.version });
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", height: "100%", overflow: "hidden" }}>
      {/* Left: config */}
      <div style={{ borderRight: "1px solid var(--line-dim)", overflowY: "auto", padding: 16 }}>
        <div className="panel-title" style={{ marginBottom: 16 }}>Strategy Builder</div>
        <div style={{
          fontSize: 9, fontFamily: "var(--mono)", color: "var(--ink-faint)",
          letterSpacing: "0.06em", marginBottom: 14,
        }}>
          Compose a deterministic, versioned strategy from building blocks.
        </div>

        <Field label="Strategy Name">
          <input style={inp} value={form.name} onChange={e => set({ name: e.target.value })} placeholder="e.g. Alpha Momentum v1" />
        </Field>
        <Field label="Description">
          <input style={inp} value={form.description} onChange={e => set({ description: e.target.value })} placeholder="Optional" />
        </Field>
        <Field label="Direction">
          <select style={sel} value={form.direction} onChange={e => set({ direction: e.target.value })}>
            {DIRECTIONS.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </Field>
        <Field label="Market Regime">
          <select style={sel} value={form.regime} onChange={e => set({ regime: e.target.value })}>
            {REGIMES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>

        <div style={{ borderTop: "1px solid var(--line-dim)", margin: "14px 0 12px", paddingTop: 12 }}>
          <div className="kicker" style={{ marginBottom: 8 }}>Risk Layer</div>
          <Field label="Stop (× ATR 14)">
            <input type="number" step="0.1" style={inp} value={form.stop_atr_mult}
              onChange={e => set({ stop_atr_mult: parseFloat(e.target.value) || 1.5 })} />
          </Field>
          <Field label="Target (× ATR 14)">
            <input type="number" step="0.1" style={inp} value={form.target_atr_mult}
              onChange={e => set({ target_atr_mult: parseFloat(e.target.value) || 3 })} />
          </Field>
          <Field label="Position Size (% equity)">
            <input type="number" step="0.5" style={inp} value={form.position_size_pct}
              onChange={e => set({ position_size_pct: parseFloat(e.target.value) || 2 })} />
          </Field>
          <Field label="Max Concurrent Positions">
            <input type="number" style={inp} value={form.max_concurrent_positions}
              onChange={e => set({ max_concurrent_positions: parseInt(e.target.value) || 5 })} />
          </Field>
          <Field label="Max Daily Loss (%)">
            <input type="number" step="0.5" style={inp} value={form.max_daily_loss_pct}
              onChange={e => set({ max_daily_loss_pct: parseFloat(e.target.value) || 3 })} />
          </Field>
          <Field label="Max Drawdown (%)">
            <input type="number" step="1" style={inp} value={form.max_drawdown_pct}
              onChange={e => set({ max_drawdown_pct: parseFloat(e.target.value) || 15 })} />
          </Field>
        </div>

        <div style={{ borderTop: "1px solid var(--line-dim)", margin: "14px 0 12px", paddingTop: 12 }}>
          <div className="kicker" style={{ marginBottom: 8 }}>Execution Layer</div>
          <Field label="Commission / share ($)">
            <input type="number" step="0.001" style={inp} value={form.commission_per_share}
              onChange={e => set({ commission_per_share: parseFloat(e.target.value) || 0 })} />
          </Field>
          <Field label="Spread (%)">
            <input type="number" step="0.001" style={inp} value={form.spread_pct}
              onChange={e => set({ spread_pct: parseFloat(e.target.value) || 0 })} />
          </Field>
          <Field label="Slippage (%)">
            <input type="number" step="0.001" style={inp} value={form.slippage_pct}
              onChange={e => set({ slippage_pct: parseFloat(e.target.value) || 0 })} />
          </Field>
        </div>

        <Button onClick={handleSave} style={{ width: "100%", justifyContent: "center", display: "flex", padding: "10px", marginTop: 8 }}>
          {saving ? "Saving…" : "Save Strategy ↗"}
        </Button>

        {error && (
          <div style={{ marginTop: 10, color: "var(--red)", fontFamily: "var(--mono)", fontSize: 11 }}>
            ✖ {error}
          </div>
        )}
        {result && (
          <div style={{ marginTop: 10, color: "var(--green)", fontFamily: "var(--mono)", fontSize: 11 }}>
            ✔ Saved — ID: {result.id.slice(0, 8)}… v{result.version}
          </div>
        )}
      </div>

      {/* Right: condition builder */}
      <div style={{ overflowY: "auto", padding: 16 }}>
        <div className="panel-title" style={{ marginBottom: 12 }}>Condition Layers</div>
        <div style={{
          fontSize: 9, fontFamily: "var(--mono)", color: "var(--ink-faint)",
          letterSpacing: "0.06em", marginBottom: 16,
        }}>
          Build each layer from deterministic indicator comparisons.
          Signal generated at prior bar's close; filled at next bar's open.
        </div>

        <Panel title="ENTRY — Entry signal conditions">
          <BlockBuilder label="Entry conditions" conditions={form.entry} logic={form.entry_logic}
            onConditions={c => set({ entry: c })} onLogic={l => set({ entry_logic: l })} />
        </Panel>

        <Panel title="FILTER — Pre-trade filters" sectionStyle={{ marginTop: 12 }}>
          <BlockBuilder label="Filter conditions" conditions={form.filter} logic={form.filter_logic}
            onConditions={c => set({ filter: c })} onLogic={l => set({ filter_logic: l })} />
        </Panel>

        <Panel title="CONFIRMATION — Additional confirmation signals" sectionStyle={{ marginTop: 12 }}>
          <BlockBuilder label="Confirmation conditions" conditions={form.confirmation} logic={form.confirmation_logic}
            onConditions={c => set({ confirmation: c })} onLogic={l => set({ confirmation_logic: l })} />
        </Panel>

        <Panel title="EXIT — Additional exit conditions (beyond stop/target)" sectionStyle={{ marginTop: 12 }}>
          <BlockBuilder label="Exit conditions" conditions={form.exit} logic={form.exit_logic}
            onConditions={c => set({ exit: c })} onLogic={l => set({ exit_logic: l })} />
        </Panel>

        {/* Preview JSON */}
        <div style={{ marginTop: 16 }}>
          <div className="kicker" style={{ marginBottom: 8 }}>Strategy JSON Preview</div>
          <pre style={{
            background: "var(--bg-3)", border: "1px solid var(--line-dim)",
            padding: 12, fontFamily: "var(--mono)", fontSize: 10,
            color: "var(--ink-dim)", overflowX: "auto", whiteSpace: "pre-wrap",
            maxHeight: 300, overflowY: "auto",
          }}>
            {JSON.stringify(form, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
