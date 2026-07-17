import React from "react";

export function PageHeader({ eyebrow, title, description, actions }: {
  eyebrow?: string; title: string; description?: string; actions?: React.ReactNode;
}) {
  return <header className="workspace-header">
    <div>
      {eyebrow && <div className="kicker">{eyebrow}</div>}
      <h1>{title}</h1>
      {description && <p>{description}</p>}
    </div>
    {actions && <div className="workspace-header-actions">{actions}</div>}
  </header>;
}

export function EvidenceBadge({ tier }: { tier: string }) {
  const normalized = tier.toLowerCase();
  const tone = normalized.includes("live") && !normalized.includes("limited") ? "live"
    : normalized.includes("paper") ? "paper"
    : normalized.includes("backtest") || normalized.includes("shadow") ? "research" : "unknown";
  return <span className={`evidence-badge ${tone}`}>{tier.split("_").join(" ")}</span>;
}

export function FreshnessLabel({ timestamp, source }: { timestamp?: string | null; source?: string }) {
  let label = "Timestamp unavailable";
  if (timestamp) {
    const parsed = new Date(timestamp);
    label = Number.isNaN(parsed.getTime()) ? "Timestamp unavailable" : parsed.toLocaleString();
  }
  return <span className="freshness-label">{source ? `${source} · ` : ""}{label}</span>;
}

export function StatusState({ kind, title, detail }: {
  kind: "loading" | "empty" | "error" | "unavailable"; title: string; detail?: string;
}) {
  return <div className={`workspace-state ${kind}`} role={kind === "error" ? "alert" : "status"}>
    <strong>{title}</strong>{detail && <span>{detail}</span>}
  </div>;
}
