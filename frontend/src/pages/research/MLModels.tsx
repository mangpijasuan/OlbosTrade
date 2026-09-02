/**
 * ML Models — status of the AI signal scorer (XGBoost regressor + SHAP
 * explainability) that scores each candidate trade's predicted return-on-risk.
 * Backed by /api/research/model-performance. See backend/app/services/signal_scorer.py.
 */
import React, { useEffect, useState } from "react";
import { Badge } from "../../components/ui";

interface ValidationMetrics {
  mae?: number;
  r2?: number;
  directional_accuracy?: number;
  n_train?: number;
  n_val?: number;
}

interface ModelPerf {
  model_version?: string;
  model_type?: string;
  model_path?: string;
  trained?: boolean;
  auc?: number | null;
  last_trained?: string | null;
  validation_metrics?: ValidationMetrics;
  retrain_schedule?: string;
  error?: string;
}

// Mirrors FEATURE_NAMES in backend/app/services/signal_scorer.py — update both
// together if the feature set changes.
const FEATURES = [
  "iv_rank", "iv_percentile", "vix_level",
  "spy_rsi_14", "spy_adx_14", "spy_trend_direction",
  "days_to_expiry", "short_strike_delta",
  "spread_width", "credit_to_width_ratio",
  "earnings_days_away", "spy_realized_vol_20d",
  "iv_minus_rv", "credit_theta_rate", "vix_term_slope",
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--line-dim)" }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</span>
      <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{children}</span>
    </div>
  );
}

export default function MLModels() {
  const [perf, setPerf] = useState<ModelPerf | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    fetch("/api/research/model-performance")
      .then(r => r.json())
      .then(d => { setPerf(d); setLoading(false); })
      .catch(() => { setPerf({ error: "unreachable" }); setLoading(false); });
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const trained = !!perf?.trained;

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">ML Models</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          {loading ? "checking…" : "signal scorer status · polls every 30s"}
        </span>
      </div>

      <div style={{ maxWidth: 520, border: "1px solid var(--line-dim)", background: "var(--bg-2)", padding: "12px 16px", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
          <span className={`dot ${trained ? "live" : "dead"}`} style={{ marginRight: 8 }} />
          <span style={{
            fontFamily: "var(--mono)", fontSize: 14, fontWeight: 600,
            color: trained ? "var(--green)" : "var(--amber)",
            textTransform: "uppercase", letterSpacing: "0.06em",
          }}>
            {trained ? "trained" : "untrained"}
          </span>
          <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
            {perf?.model_version ?? "—"}
          </span>
        </div>
        <Field label="Architecture">XGBoost regressor · SHAP explainability</Field>
        <Field label="Predicts">Return-on-risk (RoR)</Field>
        <Field label="Directional accuracy">
          {perf?.validation_metrics?.directional_accuracy != null
            ? `${(perf.validation_metrics.directional_accuracy * 100).toFixed(1)}%`
            : "—"}
        </Field>
        <Field label="R²">
          {perf?.validation_metrics?.r2 != null ? perf.validation_metrics.r2.toFixed(3) : "—"}
        </Field>
        <Field label="MAE (RoR)">
          {perf?.validation_metrics?.mae != null ? perf.validation_metrics.mae.toFixed(4) : "—"}
        </Field>
        <Field label="Train / val rows">
          {perf?.validation_metrics?.n_train != null
            ? `${perf.validation_metrics.n_train} / ${perf.validation_metrics.n_val}`
            : "—"}
        </Field>
        <Field label="Last trained">{perf?.last_trained ?? "—"}</Field>
        <Field label="Retrain schedule">{perf?.retrain_schedule ?? "—"}</Field>
        {perf?.error && <Field label="Error"><span style={{ color: "var(--red)" }}>{perf.error}</span></Field>}
      </div>

      <div style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--ink-dim)", marginBottom: 8, textTransform: "uppercase" }}>
        Input features ({FEATURES.length})
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, maxWidth: 640 }}>
        {FEATURES.map(f => (
          <Badge key={f} kind="tag" tone="var(--cyan)" style={{
            fontSize: 10.5, border: "1px solid var(--line-dim)", padding: "3px 8px", opacity: 1,
          }}>
            {f}
          </Badge>
        ))}
      </div>
    </div>
  );
}
