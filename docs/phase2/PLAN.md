# OlbosTrade Phase 2 — Implementation Plan (Scope A)

Research-driven quant platform. Built on the merged V2+V3 base. **Reuse-first**:
every batch extends existing modules rather than rebuilding. Same bar as V3 —
new pure money-path modules to ≥95% under the CI hard-gate; glue/route/UI under
the whole-app ratchet. Nothing deploys until explicitly approved.

**In scope:** Strategy Registry, Feature Store, Health 0–100 score, Meta-Strategy
layer, Dynamic Capital Allocation, Scenario/Stress + parametric VaR, Journal
Intelligence + AI Research Assistant.

**Deferred (out of scope this phase):** Multi-Tenant SaaS (auth/RBAC/billing),
full plugin marketplace runtime, historical/Monte-Carlo VaR (needs live history).

---

## Lifecycle mapping (registry vs. existing Research Lab)

The prompt's statuses map onto the existing `research_experiments` stages with one
new stage added — we do NOT create a parallel system:

| Phase-2 status | Existing stage | Action |
|---|---|---|
| Research      | `draft`       | reuse |
| Backtest      | `backtested`  | reuse |
| Walk Forward  | —             | **new** `walk_forward` stage |
| Paper Trading | `paper`       | reuse |
| Production    | `promoted`    | reuse (semantic = live-eligible) |
| Retired       | `archived`    | reuse |

---

## Batch 1 — Strategy Registry + Feature Store  (detailed)

### Strategy Registry
- **`alembic/versions/0007_extend_research_experiments_registry.py`** (new)
  Add columns to `research_experiments`: `version` (str), `author` (str),
  `asset_class` (str), `market_type` (str), `supported_regimes` (JSONB),
  `risk_profile` (str). Additive, nullable — backward compatible.
- **`app/models/research_experiment.py`** (edit) — add the mapped columns + extend
  `as_dict()`.
- **`app/services/research_lab.py`** (edit) — add `WALK_FORWARD` stage to `STAGES`
  and `ALLOWED_TRANSITIONS` (`backtested → walk_forward → paper`); add a
  walk-forward gate `evaluate_walkforward_gate()` (out-of-sample Sharpe/return vs
  in-sample degradation). Pure → keep 100%.
- **`app/services/strategy_registry.py`** (new, pure) — `StrategyRegistry` view
  over experiment dicts: filter/group by stage, `production_strategies()`,
  `registry_summary()`, metadata validation. ≥95%.
- **`app/api/routes/research.py`** (edit) — extend `/lab/experiments` create to
  accept the metadata; add `GET /api/research/registry` (canonical list + counts
  by status).
- **Tests:** `tests/test_strategy_registry.py`, extend `tests/test_research_lab.py`
  for the walk-forward stage/gate.

### Feature Store
- **`app/services/feature_store.py`** (new, pure) — `FeatureSpec(name, fn, source,
  update_frequency, validation)`, a `FEATURES` registry, `compute(name, data,
  **kw)` dispatcher, and `validate(name, value)`. Seed it with the indicators that
  already exist (rsi, sma, ema, volatility, cumulative_return, max_drawdown, atr,
  macd, volume_ratio, iv_rank, iv_percentile). ≥95%.
- **`app/services/symphony.py`** (edit) — delegate `_INDICATORS` to the feature
  store so there's ONE implementation; keep symphony's public wrappers so its
  tests stay green (no behaviour change).
- **`app/api/routes/research.py`** (edit) — `GET /api/research/features`
  (catalog: name, formula, source, freq).
- **Tests:** `tests/test_feature_store.py` (+ confirm `test_symphony.py` still
  passes against the delegated math).
- **CI:** add `feature_store`, `strategy_registry` to the hard-95 gate.

---

## Batch 2 — Health 0–100 score + Meta-Strategy layer  (outline)
- **`app/services/strategy_health.py`** (edit) — add `health_score()` → 0–100 from
  weighted components (win-rate, profit factor, Sharpe, Sortino, expectancy,
  recent perf, regime-compat, drawdown). Keep existing grade; score drives
  allocation. Extend `/api/strategy/health` payload.
- **`app/services/meta_strategy.py`** (new, pure) — reads current regime
  (`regime_classifier.REGIME_CONFIG`) + per-strategy health → `active_strategies`
  + per-strategy enable/disable + allocation tilt. ≥95%.
- **`app/api/routes/strategy.py`** (edit) — `GET /api/strategy/meta`.
- UI: Meta-Strategy panel (which strategies active + why).

## Batch 3 — Dynamic Capital Allocation Engine  (outline, the core payoff)
- **`app/services/allocation_engine.py`** (new, pure) — methods: `risk_parity`,
  `volatility_target`, `performance_weighted`, `kelly_guided`, `blended`; inputs:
  per-strategy health/vol/returns/correlation + caps (max per strategy, portfolio
  heat); output: normalized target weights respecting constraints. ≥95%.
- **`app/services/portfolio_engine.py`** (edit) — consume target weights to size
  the per-strategy capital envelope (reuses existing heat/concentration).
- **`app/api/routes/portfolio.py`** (edit) — `GET /api/portfolio/allocation`
  (current vs target weights + drift).
- UI: allocation panel (target vs actual, capital migration).

## Batch 4 — Scenario/Stress + parametric Portfolio VaR  (outline)
- **`app/services/scenario_engine.py`** (new, pure) — deterministic shocks (crash,
  IV spike, rate shock, gap up/down, flash crash) repriced through the existing BS
  pricer + Greeks; per-position and portfolio. ≥95%.
- **`app/services/portfolio_risk_sim.py`** (new, pure) — parametric VaR / Expected
  Shortfall + pre-trade impact from current Greeks/exposures. ≥95%.
- **`risk_manager.approve_trade()`** (edit) — optional pre-trade VaR/heat-impact
  rejection (additive gate, fails open).
- **`app/api/routes/risk.py`** (edit) — `GET /api/risk/scenarios`,
  `GET /api/risk/var`. UI: scenario panel.

## Batch 5 — Journal Intelligence + AI Research Assistant  (outline)
- **`app/services/journal_intelligence.py`** (new, pure) — stats over trade
  history: best/worst regimes, recurring losing setups, EV-vs-actual, hold-time
  patterns. ≥95%.
- **`app/services/llm_provider.py`** (new) — provider-agnostic LLM interface
  `LLMProvider.complete(system, prompt) -> str` with two implementations:
  `AnthropicProvider` (model `claude-opus-4-8`) and `GeminiProvider` (Google
  `google-genai`, configurable Gemini model). Selection via `LLM_PROVIDER`
  (`anthropic` | `gemini` | `auto`); `auto` picks whichever key is present.
  The prompt-building / provider-selection logic is pure and unit-tested with a
  mocked client (≥95%); the network call itself is the thin un-gated part.
- **`app/services/research_assistant.py`** (new, glue) — read-only Q&A over system
  data, grounded in registry / health / allocation / journal outputs, delegating
  to `llm_provider`. Degrades gracefully if no key is configured.
- **Config** (`app/core/config.py` + `.env.prod`) — add `LLM_PROVIDER`,
  `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, optional `LLM_MODEL` override.
  Requirements: add `google-genai` (and `anthropic` if not present).
  **Defaults (testing period = free/cheap):** `LLM_PROVIDER=gemini`,
  `LLM_MODEL` = a current Gemini **Flash** model (free-tier eligible; exact id
  confirmed at implementation time). Cost-guards: cap output tokens, short
  grounded prompts, and a simple per-session rate limit so the free tier isn't
  blown. Switching to Claude later is a one-line env change
  (`LLM_PROVIDER=anthropic`).
- **`app/api/routes/research.py`** (edit) — `POST /api/research/assistant`.
  UI: chat panel on the Research page.

---

## Cross-cutting
- **Observability** — extend `observability.py` counters into the new engines;
  add per-domain readouts to `/api/health/detail`.
- **Verified performance separation** — already separated (backtest_runs /
  experiment paper_perf / live trades); Batch 1 walk-forward adds the missing
  bucket. No mixing.
- **Backward compatibility** — every schema change additive/nullable; every
  indicator refactor keeps existing public signatures; no live-trading path is
  rewritten, only extended with additive, fail-open gates.

## Reality check
Allocation, health-score, meta-strategy, and journal-AI are data-hungry. On a
fresh paper account they start cold and sharpen as trades accrue. We build the
machinery now; it activates with data.
