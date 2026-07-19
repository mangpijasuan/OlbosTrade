/**
 * MetricHint — one-line glossary tooltips for expert trading metrics.
 * Hover (native title) explains the term without cluttering the layout.
 */
import React from "react";

/** Canonical glossary — keep wording short (one sentence). */
export const METRIC_HINTS: Record<string, string> = {
  sharpe:
    "Risk-adjusted return: how much extra return you earned per unit of volatility.",
  sortino:
    "Like Sharpe, but only penalizes downside volatility (losses), not upside moves.",
  calmar:
    "Return divided by the worst peak-to-trough drawdown — higher means better recovery from pain.",
  "max dd":
    "Largest peak-to-trough drop in portfolio value over the sample period.",
  "current dd":
    "How far the portfolio is currently below its recent peak.",
  "rolling dd (30)":
    "Worst drawdown measured inside a rolling 30-day window.",
  expectancy:
    "Average dollars you expect to make (or lose) per trade over the sample.",
  "win rate":
    "Share of closed trades that finished profitable.",
  "profit factor":
    "Gross profits divided by gross losses — above 1.0 means winners outweigh losers.",
  pop:
    "Probability of Profit — estimated chance this trade finishes in the green before exit.",
  ev:
    "Expected Value — average dollars this trade should make if the probabilities hold.",
  kelly:
    "Suggested fraction of bankroll to risk based on edge and odds (often used conservatively).",
  "p(touch)":
    "Estimated chance price reaches the short strike before expiration.",
  "Δ":
    "Delta — how much the option price tends to move when the underlying moves $1.",
  mae:
    "Maximum Adverse Excursion — the worst unrealized loss while the trade was open.",
  mfe:
    "Maximum Favorable Excursion — the best unrealized profit while the trade was open.",
  capture:
    "How much of the best unrealized profit (MFE) you actually kept at exit.",
  "slip est.":
    "Estimated cost from buying/selling away from mid price (slippage).",
  "iv rank":
    "Where current implied volatility sits versus its past year (0 = low, 100 = high).",
  "net theta":
    "Portfolio theta — approximate dollars of option time-decay earned or paid per day.",
  "net theta / day":
    "Portfolio theta — approximate dollars of option time-decay earned or paid per day.",
  "net theta (daily)":
    "Portfolio theta — approximate dollars of option time-decay earned or paid per day.",
  "consecutive losses":
    "How many losing trades in a row — guardrails may pause trading after a streak.",
  "consec. loss":
    "How many losing trades in a row — guardrails may pause trading after a streak.",
  "avg hold":
    "Average number of days positions stayed open.",
};

const DEFAULT_LABELS: Record<string, string> = {
  sharpe: "Sharpe",
  sortino: "Sortino",
  calmar: "Calmar",
  "max dd": "Max DD",
  "current dd": "Current DD",
  "rolling dd (30)": "Rolling DD (30)",
  expectancy: "Expectancy",
  "win rate": "Win Rate",
  "profit factor": "Profit Factor",
  pop: "POP",
  ev: "EV",
  kelly: "Kelly",
  "p(touch)": "P(touch)",
  "Δ": "Δ",
  mae: "MAE",
  mfe: "MFE",
  capture: "Capture",
  "slip est.": "Slip. Est.",
  "iv rank": "IV Rank",
  "net theta": "Net Theta (daily)",
  "net theta / day": "Net Theta (daily)",
  "net theta (daily)": "Net Theta (daily)",
  "consecutive losses": "Consecutive losses",
  "consec. loss": "Consecutive losses",
  "avg hold": "Avg Hold",
};

export function metricHintKey(label: string): string {
  return label.trim().toLowerCase();
}

export function resolveMetricHint(labelOrId: string): string | undefined {
  return METRIC_HINTS[metricHintKey(labelOrId)];
}

export default function MetricHint({
  id,
  children,
}: {
  /** Glossary key or display label (matched case-insensitively). */
  id: string;
  children?: React.ReactNode;
}) {
  const key = metricHintKey(id);
  const hint = METRIC_HINTS[key];
  // Prefer glossary display spelling when we have one (e.g. Consecutive losses).
  const content = children ?? DEFAULT_LABELS[key] ?? id;

  if (!hint) {
    return <>{content}</>;
  }

  return (
    <span
      title={hint}
      style={{
        cursor: "help",
        borderBottom: "1px dotted rgba(148,163,184,0.45)",
      }}
    >
      {content}
    </span>
  );
}
