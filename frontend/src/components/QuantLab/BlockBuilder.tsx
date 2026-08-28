/**
 * BlockBuilder — visual condition composer for strategy layers.
 *
 * Renders a list of ConditionBlock rows with indicator, period, operator,
 * compare_to, compare_period/value controls.  Parent passes the layer array
 * and a setter.  Supports AND / OR logic selection between conditions.
 */

import React from "react";

const INDICATORS = [
  "EMA", "SMA", "RSI", "ADX", "MACD", "MACD_SIGNAL",
  "BB_UPPER", "BB_LOWER", "BB_MID", "ATR",
  "VOLUME", "VOLUME_MA", "CLOSE", "HIGH", "LOW", "OPEN",
];

const OPERATORS = [
  { value: ">",            label: ">" },
  { value: ">=",           label: ">=" },
  { value: "<",            label: "<" },
  { value: "<=",           label: "<=" },
  { value: "==",           label: "==" },
  { value: "crosses_above", label: "crosses ↑" },
  { value: "crosses_below", label: "crosses ↓" },
];

const COMPARE_OPTIONS = ["VALUE", ...INDICATORS];

const COMMON_PERIODS = [5, 10, 14, 20, 26, 50, 100, 200];

export interface ConditionBlockDef {
  indicator:      string;
  period:         number;
  operator:       string;
  compare_to:     string;
  compare_period: number;
  value:          number;
}

interface Props {
  conditions:  ConditionBlockDef[];
  logic:       string;
  onConditions: (conds: ConditionBlockDef[]) => void;
  onLogic:     (logic: string) => void;
  label:       string;
}

const sel: React.CSSProperties = {
  background: "var(--bg-3)", border: "1px solid var(--line-dim)",
  color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 11,
  padding: "4px 6px", outline: "none", borderRadius: 2,
};

const inp: React.CSSProperties = { ...sel, width: 68 };

function emptyBlock(): ConditionBlockDef {
  return { indicator: "EMA", period: 20, operator: ">", compare_to: "EMA", compare_period: 50, value: 0 };
}

export default function BlockBuilder({ conditions, logic, onConditions, onLogic, label }: Props) {
  const update = (idx: number, patch: Partial<ConditionBlockDef>) => {
    const next = conditions.map((c, i) => i === idx ? { ...c, ...patch } : c);
    onConditions(next);
  };

  const add    = () => onConditions([...conditions, emptyBlock()]);
  const remove = (idx: number) => onConditions(conditions.filter((_, i) => i !== idx));

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span className="kicker" style={{ flex: 1 }}>{label}</span>
        {conditions.length > 1 && (
          <select style={{ ...sel, width: 60 }} value={logic} onChange={e => onLogic(e.target.value)}>
            <option value="AND">AND</option>
            <option value="OR">OR</option>
          </select>
        )}
        <button onClick={add} style={{
          background: "none", border: "1px solid var(--cyan)", color: "var(--cyan)",
          fontFamily: "var(--mono)", fontSize: 10, padding: "2px 8px", cursor: "pointer", borderRadius: 2,
        }}>+ Add</button>
      </div>

      {conditions.length === 0 && (
        <div style={{ color: "var(--ink-faint)", fontSize: 11, fontFamily: "var(--mono)" }}>
          No conditions — click + Add
        </div>
      )}

      {conditions.map((c, idx) => (
        <div key={idx} style={{
          display: "flex", alignItems: "center", gap: 6, marginBottom: 5,
          padding: "6px 8px", background: "var(--bg-3)", border: "1px solid var(--line-dim)",
        }}>
          {/* Indicator */}
          <select style={sel} value={c.indicator} onChange={e => update(idx, { indicator: e.target.value })}>
            {INDICATORS.map(i => <option key={i} value={i}>{i}</option>)}
          </select>

          {/* Period */}
          <select style={{ ...sel, width: 58 }} value={c.period} onChange={e => update(idx, { period: Number(e.target.value) })}>
            {COMMON_PERIODS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>

          {/* Operator */}
          <select style={sel} value={c.operator} onChange={e => update(idx, { operator: e.target.value })}>
            {OPERATORS.map(op => <option key={op.value} value={op.value}>{op.label}</option>)}
          </select>

          {/* Compare to */}
          <select style={{ ...sel, width: 90 }} value={c.compare_to} onChange={e => update(idx, { compare_to: e.target.value })}>
            {COMPARE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
          </select>

          {/* Compare period (if not VALUE) */}
          {c.compare_to !== "VALUE" ? (
            <select style={{ ...sel, width: 58 }} value={c.compare_period}
              onChange={e => update(idx, { compare_period: Number(e.target.value) })}>
              {COMMON_PERIODS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          ) : (
            <input type="number" style={inp} value={c.value}
              onChange={e => update(idx, { value: parseFloat(e.target.value) || 0 }) } />
          )}

          {/* Remove */}
          <button onClick={() => remove(idx)} style={{
            background: "none", border: "none", color: "var(--red)",
            cursor: "pointer", fontSize: 14, lineHeight: 1, padding: "0 4px",
          }}>×</button>
        </div>
      ))}
    </div>
  );
}
