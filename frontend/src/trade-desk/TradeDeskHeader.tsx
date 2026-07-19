/**
 * Trade Desk header — environment, mode, risk profile, broker, P&L, kill switch.
 * Read-only display + mode switch via existing APIs. Paper/Live always labeled (not color-only).
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import KillSwitchButton from "../components/KillSwitchButton";

type Snap = { label: string; value: string; tone?: "ok" | "warn" | "crit" | "muted" };

function Chip({ label, value, tone = "muted" }: Snap) {
  const color =
    tone === "ok" ? "var(--green)" :
    tone === "warn" ? "var(--amber)" :
    tone === "crit" ? "var(--red)" :
    "var(--ink-dim)";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 2,
        padding: "4px 10px",
        borderRight: "1px solid var(--line-dim)",
        minWidth: 0,
      }}
    >
      <span
        style={{
          fontFamily: "var(--mono)",
          fontSize: 9,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "var(--ink-faint)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: "var(--mono)",
          fontSize: 11,
          fontWeight: 600,
          color,
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </span>
    </div>
  );
}

export default function TradeDeskHeader() {
  const [env, setEnv] = useState<"Paper" | "Live" | "Unknown">("Unknown");
  const [broker, setBroker] = useState("—");
  const [brokerStatus, setBrokerStatus] = useState("—");
  const [execMode, setExecMode] = useState("—");
  const [riskProfile, setRiskProfile] = useState("—");
  const [dayPnl, setDayPnl] = useState<string>("—");
  const [heat, setHeat] = useState("—");
  const [drawdown, setDrawdown] = useState("—");
  const [ks, setKs] = useState<"Engaged" | "Clear" | "Unknown">("Unknown");
  const [regime, setRegime] = useState("—");

  useEffect(() => {
    let alive = true;
    const load = () => {
      fetch("/api/market/broker")
        .then((r) => r.json())
        .then((d) => {
          if (!alive) return;
          setBroker((d.broker || "ibkr").toUpperCase());
          setBrokerStatus(d.status || "unknown");
          setEnv(d.paper_mode === false ? "Live" : d.paper_mode === true ? "Paper" : "Unknown");
        })
        .catch(() => {
          if (alive) {
            setBroker("Unavailable");
            setEnv("Unknown");
          }
        });

      api.getExecutionMode()
        .then((d: any) => { if (alive) setExecMode((d.mode || "—").toUpperCase()); })
        .catch(() => { if (alive) setExecMode("Unavailable"); });

      api.getCurrentMode()
        .then((d: any) => { if (alive) setRiskProfile((d.mode || "—").toUpperCase()); })
        .catch(() => { if (alive) setRiskProfile("Unavailable"); });

      api.getPortfolioState()
        .then((d: any) => {
          if (!alive) return;
          const s = d.state || d;
          const pnl = s.daily_pnl ?? s.daily_loss_pct;
          if (typeof s.daily_pnl === "number") {
            setDayPnl(`${s.daily_pnl >= 0 ? "+" : ""}$${s.daily_pnl.toFixed(0)}`);
          } else if (typeof s.daily_loss_pct === "number") {
            setDayPnl(`${(s.daily_loss_pct * 100).toFixed(2)}% loss`);
          } else {
            setDayPnl("—");
          }
          if (typeof s.daily_loss_pct === "number" && typeof s.max_daily_loss_pct === "number") {
            const rem = Math.max(0, s.max_daily_loss_pct - s.daily_loss_pct);
            setHeat(`${(rem * 100).toFixed(1)}% budget`);
            setDrawdown(`${(s.daily_loss_pct * 100).toFixed(2)}% day`);
          } else {
            setHeat("—");
            setDrawdown("—");
          }
          void pnl;
        })
        .catch(() => {
          if (alive) {
            setDayPnl("Unavailable");
            setHeat("Unavailable");
            setDrawdown("Unavailable");
          }
        });

      api.getTradeDeskKillSwitch()
        .then((d: any) => {
          if (!alive) return;
          setKs(d.engaged ? "Engaged" : "Clear");
        })
        .catch(() => {
          api.getKillSwitchStatus()
            .then((d: any) => {
              if (!alive) return;
              setKs(d.engaged || d.is_engaged ? "Engaged" : "Clear");
            })
            .catch(() => { if (alive) setKs("Unknown"); });
        });

      api.getRegime()
        .then((d: any) => {
          if (!alive) return;
          const r = d.regime || d.regime_type || d.type;
          setRegime(typeof r === "string" ? r.replace(/_/g, " ") : "—");
        })
        .catch(() => { if (alive) setRegime("Unavailable"); });
    };

    load();
    const t = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const envTone = env === "Live" ? "crit" : env === "Paper" ? "ok" : "warn";
  const ksTone = ks === "Engaged" ? "crit" : ks === "Clear" ? "ok" : "warn";
  const brokerTone =
    brokerStatus === "connected" || brokerStatus === "ok" ? "ok" :
    brokerStatus === "disconnected" ? "warn" : "muted";

  return (
    <header
      style={{
        display: "flex",
        alignItems: "stretch",
        flexWrap: "wrap",
        background: "var(--bg-2)",
        borderBottom: "1px solid var(--line-dim)",
        flexShrink: 0,
      }}
      aria-label="Trade Desk status"
    >
      <Chip label="Environment" value={env} tone={envTone} />
      <Chip label="Execution" value={execMode} tone={execMode === "AUTOPILOT" ? "warn" : "muted"} />
      <Chip label="Risk profile" value={riskProfile} />
      <Chip label="Broker" value={`${broker} · ${brokerStatus}`} tone={brokerTone} />
      <Chip label="Regime" value={regime} />
      <Chip label="Day P&L" value={dayPnl} tone={dayPnl.startsWith("-") || dayPnl.includes("loss") ? "crit" : "ok"} />
      <Chip label="Risk budget" value={heat} />
      <Chip label="Drawdown" value={drawdown} />
      <Chip label="Kill switch" value={ks} tone={ksTone} />
      <div style={{ flex: 1, minWidth: 8 }} />
      <div style={{ display: "flex", alignItems: "center", padding: "4px 8px" }}>
        <KillSwitchButton variant="panel" />
      </div>
    </header>
  );
}
