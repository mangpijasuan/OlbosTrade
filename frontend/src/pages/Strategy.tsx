import React, { useState } from "react";

type StrategyCard = {
  strategy_id: string;
  name: string;
  version: string;
  asset_class: string;
  supported_symbols: string[];
  supported_regimes: string[];
  supported_volatility_regimes: string[];
  risk_profile_compatibility: string[];
  eligibility: { manual: boolean; copilot: boolean; autopilot: boolean };
  autopilot_block_reason?: string | null;
  lifecycle_status: string;
  health_score: number | null;
  last_validation_date: string | null;
  allocation_limit_pct: number | null;
  enabled: boolean;
  main_risk_warning: string | null;
  validation_notes?: string | null;
};

type StrategyPreset = {
  preset_id: string;
  strategy_id: string;
  category: string;
  preset_name: string;
  version: string;
  timeframe: string;
  confidence_threshold: number;
  max_allocation_pct: number;
  validation_status: string;
  paper_validated: boolean;
  live_validated: boolean;
  approval_notes?: string | null;
};

type StrategySnapshot = {
  snapshot_id: string;
  strategy_id: string;
  preset_id?: string | null;
  label: string;
  risk_profile: string;
  lifecycle_status: string;
  validation_status: string;
  is_active: boolean;
  inherited_from_verified_preset: boolean;
  created_by: string;
  created_at?: string | null;
};

// Execution-mode eligibility pill — distinct colored fill per mode when eligible,
// muted when not. Manual=slate, Copilot=blue, Auto=green.
const MODE_TONE: Record<string, string> = {
  manual: "148,163,184",   // slate
  copilot: "59,130,246",   // blue
  autopilot: "34,197,94",  // green
};
function ModeTag({ label, mode, on }: { label: string; mode: string; on: boolean }) {
  const rgb = MODE_TONE[mode];
  return (
    <span style={{
      flex: 1, textAlign: "center", fontSize: 10, fontWeight: 500,
      padding: "2px 0", borderRadius: 3,
      background: on ? `rgba(${rgb},0.18)` : "transparent",
      color: on ? `rgb(${rgb})` : "var(--ink-faint)",
      border: `1px solid ${on ? `rgba(${rgb},0.4)` : "var(--line-dim)"}`,
    }}>{label}</span>
  );
}

const statusColor = (status: string) => {
  switch (status) {
    case "autopilot_eligible":
      return "var(--green)";
    case "limited_live_validation":
      return "var(--blue)";
    case "paper_validated":
      return "var(--cyan)";
    case "walk_forward_passed":
      return "var(--amber)";
    case "paused":
    case "retired":
      return "var(--red)";
    default:
      return "var(--ink-dim)";
  }
};

const formatStatus = (value: string) => value.replace(/_/g, " ").toUpperCase();
const formatTitle = (value: string) =>
  value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
const formatSentence = (value: string) =>
  formatTitle(value.replace(/[:.-]+/g, " ").replace(/\s+/g, " ").trim());
const formatPercent = (value: number | null, digits = 0) =>
  value === null ? "\u2014" : `${(value * 100).toFixed(digits)}%`;

export default function Strategy() {
  const [tab, setTab] = useState<"registry" | "backtest">("registry");
  const [strategies, setStrategies] = useState<StrategyCard[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [presets, setPresets] = useState<StrategyPreset[]>([]);
  const [snapshots, setSnapshots] = useState<StrategySnapshot[]>([]);
  const [snapshotStatus, setSnapshotStatus] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const loadRegistry = async () => {
      try {
        const data: any = await api.getStrategyRegistry();
        if (!alive) return;
        const rows = data.strategies || [];
        setStrategies(rows);
        setSelected(rows[0]?.strategy_id || "");
        setError(null);
      } catch (err: any) {
        // Fallback for cases where the app is pointed at an older backend route set.
        try {
          const fallback: any = await api.getStrategyConfig();
          if (!alive) return;
          const rows = fallback.strategies || [];
          setStrategies(rows);
          setSelected(rows[0]?.strategy_id || "");
          setError(null);
        } catch (fallbackErr: any) {
          if (!alive) return;
          setError(
            fallbackErr.message || err?.message || "Could not load strategy registry"
          );
        }
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    };
    loadRegistry();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    setSnapshotStatus(null);
    Promise.all([
      api.getStrategyPresets(selected),
      api.getStrategySnapshots(selected),
    ])
      .then(([presetData, snapshotData]: any) => {
        if (!alive) return;
        setPresets(presetData.presets || []);
        setSnapshots(snapshotData.snapshots || []);
      })
      .catch((err: Error) => {
        if (!alive) return;
        setPresets([]);
        setSnapshots([]);
        setSnapshotStatus(err.message || "Could not load presets and snapshots");
      });
    return () => { alive = false; };
  }, [selected]);

  const strat = strategies.find(s => s.strategy_id === selected) || strategies[0];
  const activeSnapshot = snapshots.find(s => s.is_active) || null;

  const restoreSnapshot = async (snapshotId: string) => {
    setSnapshotStatus("Restoring snapshot…");
    try {
      await api.restoreStrategySnapshot(snapshotId);
      const refreshed: any = await api.getStrategySnapshots(selected);
      setSnapshots(refreshed.snapshots || []);
      setSnapshotStatus("Active snapshot updated.");
    } catch (err: any) {
      setSnapshotStatus(err.message || "Could not restore snapshot");
    }
  };

  const saveFromTopPreset = async () => {
    if (!strat || presets.length === 0) return;
    const preset = presets[0];
    setSnapshotStatus("Saving snapshot from verified preset…");
    try {
      await api.createStrategySnapshot({
        strategy_id: strat.strategy_id,
        preset_id: preset.preset_id,
        label: `${preset.preset_name} Custom Snapshot`,
        notes: "Created from Strategy page baseline preset",
        risk_profile: strat.risk_profile_compatibility[0] || "balanced",
        lifecycle_status: strat.lifecycle_status,
        validation_status: "custom",
        config_payload: {
          preset_id: preset.preset_id,
          timeframe: preset.timeframe,
          confidence_threshold: preset.confidence_threshold,
          max_allocation_pct: preset.max_allocation_pct,
        },
        created_by: "operator",
        activate: true,
      });
      const refreshed: any = await api.getStrategySnapshots(selected);
      setSnapshots(refreshed.snapshots || []);
      setSnapshotStatus("Custom snapshot saved and activated.");
    } catch (err: any) {
      setSnapshotStatus(err.message || "Could not create snapshot");
    }
  };

  const renderChipGroup = (
    items: string[],
    emptyLabel: string,
    formatter: (value: string) => string = formatStatus
  ) => {
    if (items.length === 0) {
      return (
        <div style={{ fontSize: 12, color: "var(--ink-faint)", lineHeight: 1.6 }}>
          {emptyLabel}
        </div>
      );
    }

    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((item) => (
          <span
            key={item}
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10,
              padding: "2px 7px",
              border: "1px solid var(--line-dim)",
              color: "var(--ink-dim)",
            }}
          >
            {formatter(item)}
          </span>
        ))}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Algo Engine tabs — Registry (manage strategies) / Backtest (validate). */}
      <div style={{
        padding: "6px 14px", borderBottom: "1px solid var(--line-dim)",
        background: "var(--bg-2)", display: "flex", alignItems: "center", gap: 8,
      }}>
        <button className={`btn-t ${tab === "registry" ? "active" : ""}`} onClick={() => setTab("registry")}>Registry</button>
        <button className={`btn-t ${tab === "backtest" ? "active" : ""}`} onClick={() => setTab("backtest")}>Backtest</button>
      </div>

      {tab === "backtest" ? (
        <div style={{ flex: 1, overflow: "hidden" }}><Backtest /></div>
      ) : (
      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", flex: 1, overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--line-dim)", background: "var(--bg-2)", overflowY: "auto" }}>
        <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
          <span className="panel-title">Strategy Registry</span>
        </div>
        {loading && (
          <div style={{ padding: 16, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
            LOADING STRATEGY CARDS…
          </div>
        )}
        {error && (
          <div style={{ padding: 16, fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>
            {error}
          </div>
        )}
        {strategies.map((s) => (
          <button
            key={s.strategy_id}
            onClick={() => setSelected(s.strategy_id)}
            style={{
              width: "100%",
              padding: "9px 14px",
              textAlign: "left",
              background: selected === s.strategy_id ? "var(--fill-active)" : "transparent",
              border: "none",
              borderLeft: selected === s.strategy_id ? "2px solid var(--accent)" : "2px solid transparent",
              borderBottom: "1px solid var(--line-dim)",
              cursor: "pointer",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, color: "var(--ink)", lineHeight: 1.35 }}>
                  {s.name}
                </div>
                <div style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 2 }}>
                  {formatTitle(s.asset_class)} · v{s.version} · Health <span className="tnum">{s.health_score ?? "—"}</span> · {s.enabled ? "Enabled" : "Disabled"}
                </div>
              </div>
              <span style={{
                fontSize: 10, padding: "1px 6px", borderRadius: 3,
                color: statusColor(s.lifecycle_status),
                border: `1px solid ${statusColor(s.lifecycle_status)}55`,
                alignSelf: "start", whiteSpace: "nowrap",
              }}>
                {formatStatus(s.lifecycle_status)}
              </span>
            </div>
            <div style={{ display: "flex", gap: 5 }}>
              <ModeTag label="Manual" mode="manual" on={s.eligibility.manual} />
              <ModeTag label="Copilot" mode="copilot" on={s.eligibility.copilot} />
              <ModeTag label="Auto" mode="autopilot" on={s.eligibility.autopilot} />
            </div>
          </button>
        ))}
      </div>

      {/* Detail — Strategy Details promoted to the top; fills the freed space */}
      <div style={{ overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Strategy Details (now the primary block at the top) */}
        <div>
          <div className="kicker" style={{ marginBottom: 8 }}>Strategy Details</div>
          <h2 style={{ fontFamily: "var(--mono)", fontSize: 24, fontWeight: 600, color: "var(--cyan)", marginBottom: 6 }}>
            {strat.label}
          </h2>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {[strat.type, strat.bias, `${strat.legs} LEGS`].map(tag => (
              <span key={tag} style={{
                fontFamily: "var(--mono)", fontSize: 10, padding: "2px 8px",
                border: "1px solid var(--line-dim)", color: "var(--ink-dim)",
              }}>{tag}</span>
            ))}
          </div>
        </div>

        {/* Key metrics — responsive grid (wraps cleanly, no fixed columns) */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 1, border: "1px solid var(--line-dim)" }}>
          {[
            { label: "Max Profit", val: strat.max_profit, color: "var(--green)" },
            { label: "Max Loss",   val: strat.max_loss,   color: "var(--red)" },
            { label: "Bias",       val: strat.bias,        color: "var(--amber)" },
          ].map(m => (
            <div key={m.label} style={{ padding: "18px 20px", background: "var(--bg-2)" }}>
              <div className="kicker" style={{ marginBottom: 6 }}>{m.label}</div>
              <div className="data-val sm" style={{ color: m.color }}>{m.val}</div>
            </div>

        {/* Current Signals — grows to fill the reclaimed vertical space */}
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--line-dim)", padding: 16, flex: 1, display: "flex", flexDirection: "column", minHeight: 200 }}>
          <div className="panel-title" style={{ marginBottom: 12 }}>Current Signals</div>
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
            NO SIGNALS — WAITING FOR 09:35 ET
          </div>
        </div>
      </div>
    </div>
      )}
    </div>
  );
}
