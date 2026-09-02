import React, { useEffect, useState } from "react";
import { api } from "../../api/client";
import { EvidenceBadge, FreshnessLabel, PageHeader, StatusState } from "../../components/Workspace";
import { Button } from "../../components/ui";

type Factor = { name: string; score: number };
type Scenario = {
  key: "bull" | "base" | "bear";
  name: string;
  probability: number;
  return_range: { lower_pct: number; upper_pct: number };
  price_range: { lower: number; upper: number };
  volatility_assumption_pct: number;
  strategy_compatibility: string[];
};
type Forecast = {
  symbol: string;
  horizon_days: number;
  generated_at: string;
  evidence_tier: string;
  execution_eligible: false;
  status: string;
  confidence: "HIGH" | "MEDIUM" | "LOW" | "ABSTAIN";
  abstain: boolean;
  abstain_reasons: string[];
  probabilities: { bull: number; base: number; bear: number };
  expected_range: null | { lower_pct: number; upper_pct: number; lower_price: number; upper_price: number };
  current_price: number | null;
  expected_volatility_pct: number | null;
  model_agreement: number;
  data_quality: number;
  factors: { positive: Factor[]; negative: Factor[] };
  model_evidence: { model: string; bull_probability: number }[];
  scenarios: Scenario[];
  outcome_definition: { version: string; bull: string; base: string; bear: string };
  disclaimer: string;
};

const SYMBOLS = ["QQQ", "SPY", "NVDA", "AAPL", "MSFT"];
const HORIZONS = [1, 3, 5, 10, 20];

function pct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function ScenarioCard({ item }: { item: Scenario }) {
  const descriptions = {
    bull: "Trend continuation with improving participation.",
    base: "Consolidation inside the expected volatility band.",
    bear: "Support failure with weakening participation.",
  };
  return (
    <article className={`forecast-scenario ${item.key}`}>
      <div className="forecast-section-head">
        <div className="panel-title">{item.name}</div>
        <strong className="tnum">{item.probability}%</strong>
      </div>
      <p className="forecast-muted">{descriptions[item.key]}</p>
      <div className="forecast-range">
        <span>{pct(item.return_range.lower_pct)} to {pct(item.return_range.upper_pct)}</span>
        <span className="forecast-muted">${item.price_range.lower.toFixed(2)}–${item.price_range.upper.toFixed(2)}</span>
      </div>
      <div>
        <div className="kicker">Strategy compatibility</div>
        <div className="forecast-tags">{item.strategy_compatibility.map(value => <span key={value}>{value}</span>)}</div>
      </div>
      <div className="forecast-muted">Volatility assumption: {item.volatility_assumption_pct.toFixed(1)}%</div>
    </article>
  );
}

function FactorRows({ factors }: { factors: { positive: Factor[]; negative: Factor[] } }) {
  const rows = [...factors.positive, ...factors.negative].sort((a, b) => Math.abs(b.score) - Math.abs(a.score));
  if (!rows.length) return <div className="empty-state">Factor evidence unavailable.</div>;
  return <div className="forecast-factors">{rows.map(factor => (
    <div className="forecast-factor" key={factor.name}>
      <span>{factor.name}</span>
      <div className="forecast-factor-track"><span className={factor.score >= 0 ? "positive" : "negative"} style={{ width: `${Math.min(100, Math.abs(factor.score) * 7)}%` }} /></div>
      <strong className={`tnum ${factor.score >= 0 ? "pos" : "neg"}`}>{factor.score > 0 ? "+" : ""}{factor.score}</strong>
    </div>
  ))}</div>;
}

export default function ScenarioLab() {
  const [symbol, setSymbol] = useState("QQQ");
  const [horizon, setHorizon] = useState(5);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    api.getForecast<Forecast>(symbol, horizon)
      .then(data => { if (!cancelled) setForecast(data); })
      .catch((err: Error) => { if (!cancelled) setError(err.message || "Forecast unavailable"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol, horizon, refreshKey]);

  return (
    <div className="scenario-lab">
      <PageHeader eyebrow="Research / Scenario Lab" title="Probabilistic Intelligence"
        description="Scenario-based market intelligence with risk-aware trade eligibility."
        actions={<div className="forecast-badges"><span>Research only</span><span>Execution disabled</span></div>} />

      <div className="forecast-controls panel">
        <label>Symbol<select value={symbol} onChange={event => setSymbol(event.target.value)}>{SYMBOLS.map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Horizon<select value={horizon} onChange={event => setHorizon(Number(event.target.value))}>{HORIZONS.map(value => <option value={value} key={value}>{value} trading day{value === 1 ? "" : "s"}</option>)}</select></label>
        <Button active onClick={() => setRefreshKey(value => value + 1)} disabled={loading}>{loading ? "Refreshing…" : "Refresh outlook"}</Button>
      </div>

      {error && <StatusState kind="error" title="Forecast unavailable" detail={error} />}
      {loading && !forecast && <StatusState kind="loading" title="Building the read-only scenario outlook…" />}

      {forecast && <div className="forecast-workspace" aria-busy={loading}>
        <main className="forecast-main">
          <section className="panel forecast-outlook">
            <div className="forecast-section-head">
              <div><div className="kicker">Defined-outcome forecast</div><h2><span className="mono">{forecast.symbol}</span> · {forecast.horizon_days} trading day{forecast.horizon_days === 1 ? "" : "s"}</h2></div>
              <div className="forecast-badges"><span className={forecast.confidence.toLowerCase()}>{forecast.confidence} confidence</span><EvidenceBadge tier={forecast.evidence_tier} /><FreshnessLabel timestamp={forecast.generated_at} source="Daily market data" /></div>
            </div>

            {forecast.abstain ? <div className="forecast-abstain"><strong>ABSTAIN</strong><ul>{forecast.abstain_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></div> : <div className="forecast-probabilities" aria-label="Scenario probabilities">
              {(["bull", "base", "bear"] as const).map(key => <div className="forecast-probability" key={key}><span>{key === "base" ? "Sideways" : key[0].toUpperCase() + key.slice(1)}</span><div><i className={key} style={{ width: `${forecast.probabilities[key]}%` }} /></div><strong className="tnum">{forecast.probabilities[key]}%</strong></div>)}
            </div>}

            <div className="forecast-metrics">
              <div><span>Expected range</span><strong className="tnum">{forecast.expected_range ? `${pct(forecast.expected_range.lower_pct)} to ${pct(forecast.expected_range.upper_pct)}` : "Unavailable"}</strong><small>{forecast.expected_range ? `$${forecast.expected_range.lower_price.toFixed(2)}–$${forecast.expected_range.upper_price.toFixed(2)}` : "Insufficient evidence"}</small></div>
              <div><span>Model agreement</span><strong className="tnum">{forecast.model_agreement} / 100</strong><small>Baseline ensemble alignment</small></div>
              <div><span>Data quality</span><strong className="tnum">{forecast.data_quality} / 100</strong><small>{forecast.evidence_tier.split("_").join(" ")}</small></div>
            </div>
          </section>

          <section>
            <div className="forecast-section-head"><div><div className="kicker">Plausible outcomes</div><h2>Scenario map</h2></div><span className="forecast-muted">Not guaranteed paths</span></div>
            <div className="forecast-scenarios">{forecast.scenarios.map(item => <ScenarioCard item={item} key={item.key} />)}</div>
          </section>

          <section className="panel forecast-panel-body">
            <div className="forecast-section-head"><div><div className="kicker">Explainability</div><div className="panel-title">Forecast factors</div></div><span className="forecast-muted">Market factors only</span></div>
            <FactorRows factors={forecast.factors} />
          </section>
        </main>

        <aside className="forecast-rail">
          <section className="panel forecast-decision">
            <div className="kicker">Decision status</div><h2>{forecast.status.split("_").join(" ")}</h2>
            <p>Forecast evidence can inform research. It cannot independently authorize a trade.</p>
            <div className="forecast-line"><span>Execution</span><strong>Blocked</strong></div>
            <div className="forecast-line"><span>Evidence</span><strong>{forecast.evidence_tier.split("_").join(" ")}</strong></div>
            <div className="forecast-line"><span>Outcome rules</span><strong>{forecast.outcome_definition.version}</strong></div>
          </section>
          <section className="panel forecast-panel-body">
            <div className="panel-title">Model evidence</div>
            {forecast.model_evidence.length ? forecast.model_evidence.map(model => <div className="forecast-line" key={model.model}><span>{model.model}</span><strong className="tnum">{model.bull_probability}% bull</strong></div>) : <div className="empty-state">Unavailable while abstaining.</div>}
          </section>
          <section className="panel forecast-panel-body">
            <div className="panel-title">Outcome definition</div>
            <div className="forecast-line"><span>Bull</span><strong>{forecast.outcome_definition.bull}</strong></div>
            <div className="forecast-line"><span>Sideways</span><strong>{forecast.outcome_definition.base}</strong></div>
            <div className="forecast-line"><span>Bear</span><strong>{forecast.outcome_definition.bear}</strong></div>
          </section>
        </aside>
        <p className="forecast-disclaimer">{forecast.disclaimer}</p>
      </div>}
    </div>
  );
}
