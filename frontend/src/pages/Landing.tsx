/**
 * Landing — public marketing page. Distinct layout from the terminal shell
 * (TerminalLayout.tsx), same design tokens (index.css). Fetches no trading
 * data and calls no authenticated endpoint — safe for unauthenticated
 * visitors, since this repository has no authentication system at all (see
 * CHANGELOG for that finding).
 *
 * Every claim below is grounded in repository evidence (README.md,
 * TRADING_POLICY.md, ARCHITECTURE_MEMO.md, and the routes/services they
 * describe) rather than the original task's specification defaults —
 * several spec-provided claims (Tradier, an XGBoost regime classifier) do
 * not match the codebase and are intentionally not repeated here. See the
 * implementation report for the full claim-verification table.
 */
import React, { useState } from "react";
import { Link } from "react-router-dom";
import "../landing.css";

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <a href={href}>{children}</a>;
}

function PipelineStage({ n, title, detail }: { n: string; title: string; detail: string }) {
  return (
    <div className="pipeline-stage">
      <div className="pipeline-stage-num">{n}</div>
      <div className="pipeline-stage-title">{title}</div>
      <div className="pipeline-stage-detail">{detail}</div>
    </div>
  );
}

function Cell({ title, body }: { title: string; body: string }) {
  return (
    <div className="landing-cell">
      <div className="landing-cell-title">{title}</div>
      <div className="landing-cell-body">{body}</div>
    </div>
  );
}

function Metric({ label, value, placeholder = true }: { label: string; value: string; placeholder?: boolean }) {
  return (
    <div className="landing-cell">
      <div className="landing-metric-value">{value}</div>
      <div className="landing-metric-label">{label}</div>
      {placeholder && <div className="landing-placeholder-tag">Awaiting verified history</div>}
    </div>
  );
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-container landing-nav-row">
          <span className="landing-wordmark">OLBOS</span>
          <nav
            id="landing-nav-links"
            className={`landing-nav-links${menuOpen ? " open" : ""}`}
            aria-label="Primary"
          >
            <NavLink href="#product">Product</NavLink>
            <NavLink href="#how">How It Works</NavLink>
            <NavLink href="#risk">Risk Controls</NavLink>
            <NavLink href="#track-record">Track Record</NavLink>
          </nav>
          <div className="landing-nav-actions">
            <Link className="landing-signin" to="/terminal">Sign In</Link>
            <Link className="landing-cta-btn" to="/terminal">Start Paper Trading</Link>
            <button
              type="button"
              className="landing-nav-toggle"
              aria-expanded={menuOpen}
              aria-controls="landing-nav-links"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              onClick={() => setMenuOpen((o) => !o)}
            >
              {menuOpen ? "✕" : "☰"}
            </button>
          </div>
        </div>
      </header>

      <main>
        {/* ── Hero ──────────────────────────────────────────────────────── */}
        <section className="landing-section landing-hero" id="product">
          <div className="landing-container">
            <div className="landing-eyebrow">Systematic SPY Options Execution</div>
            <h1 className="landing-h1">
              Systematic SPY options execution with risk controls built into every decision.
            </h1>
            <p className="landing-lede">
              OlbosTrade runs a rules-based options and equity workflow — regime detection, a
              trained signal model, and a fail-closed risk gate — in front of every trade
              decision. Nothing executes without passing guardrails, and every signal shows
              where it came from. Currently in paper-trading evaluation; live capital requires a
              validated track record first.
            </p>
            <div className="landing-hero-ctas">
              <Link className="landing-cta-btn" to="/terminal">Start Paper Trading</Link>
              <a className="landing-cta-btn secondary" href="#risk">See risk controls</a>
            </div>

            <div className="pipeline" role="img" aria-label="Execution pipeline: market inputs, regime detection, risk-gated evaluation, controlled execution and audit">
              <PipelineStage
                n="01"
                title="Market inputs"
                detail="SPY price/volatility data and account state, decoupled from execution."
              />
              <PipelineStage
                n="02"
                title="Regime detection"
                detail="Rule-based VIX/ADX classification into four regimes; strategy eligibility follows the regime."
              />
              <PipelineStage
                n="03"
                title="Risk-gated evaluation"
                detail="Trained signal model, POP/EV thresholds, Kelly-informed sizing, and hard loss limits — all must pass."
              />
              <PipelineStage
                n="04"
                title="Controlled execution & audit"
                detail="Manual, Copilot, or Autopilot dispatch, with every decision written to a trade journal and execution log."
              />
            </div>
          </div>
        </section>

        {/* ── How it works ─────────────────────────────────────────────── */}
        <section className="landing-section" id="how">
          <div className="landing-container">
            <div className="landing-eyebrow">How It Works</div>
            <h2 className="landing-h2">From market data to a gated decision</h2>
            <p className="landing-lede">
              Every step below exists in the running system today — described at the level the
              codebase actually implements it, not aspirationally.
            </p>
            <div className="landing-grid-4">
              <Cell title="1. Market inputs" body="SPY/QQQ/IWM and related market data feed the scanners and regime classifier, independent of the broker connection used for order execution." />
              <Cell title="2. Regime detection" body="A VIX/ADX-based classifier buckets the market into four regimes every scan cycle; each regime allows or restricts specific strategies." />
              <Cell title="3. Risk-gated evaluation" body="A trained scoring model ranks candidates; guardrails (daily/weekly/monthly loss limits, position caps, cooling-off periods) and Kelly-informed sizing run before anything is eligible." />
              <Cell title="4. Controlled execution" body="Manual mode only generates signals. Copilot queues them for human approval. Autopilot executes only signals that clear every gate above — and a kill switch halts new orders at any time." />
            </div>
          </div>
        </section>

        {/* ── Risk controls ─────────────────────────────────────────────── */}
        <section className="landing-section" id="risk">
          <div className="landing-container">
            <div className="landing-eyebrow">Risk Controls</div>
            <h2 className="landing-h2">Automation should increase discipline, not remove oversight.</h2>
            <div className="landing-grid-3">
              <Cell title="Position sizing" body="Fractional-Kelly and volatility-based sizing, applied per trade before submission." />
              <Cell title="Drawdown limits" body="Hard daily, weekly, and monthly loss limits, enforced by the guardrail service — not a UI suggestion." />
              <Cell title="Kill switch" body="One control halts new order submission immediately and asks the broker layer to cancel open orders and flatten positions." />
              <Cell title="Live vs. paper visibility" body="The operator terminal always shows which broker and environment (paper or live) is active — never inferred silently." />
              <Cell title="Signal attribution" body="Every directional signal in the terminal shows its source, timeframe, confidence, and freshness — a bare BUY/SELL label is treated as a defect." />
              <Cell title="Divergence disclosure" body="When two independently-computed signals for the same symbol disagree, the terminal shows the disagreement explicitly instead of resolving it visually." />
              <Cell title="Manual oversight" body="Autopilot can be turned off at any time; Manual and Copilot modes keep a human in the approval loop." />
              <Cell title="Explainability" body="The signal model's training pipeline runs a SHAP-based economic-direction check at train time and on live signals, to catch backwards feature logic." />
              <Cell title="No validated track record yet" body="OlbosTrade has not completed a validated paper-trading evaluation period. We say so plainly instead of implying otherwise." />
            </div>
          </div>
        </section>

        {/* ── Metrics ───────────────────────────────────────────────────── */}
        <section className="landing-section" id="track-record">
          <div className="landing-container">
            <div className="landing-eyebrow">Track Record</div>
            <h2 className="landing-h2">Published only once verified</h2>
            <p className="landing-lede">
              We do not publish performance numbers that mix backtest, paper, and live results,
              and we do not publish anything before it is verifiable. The fields below are
              placeholders until a track record exists.
            </p>
            <div className="landing-grid-4">
              <Metric label="Live since" value="Not published" />
              <Metric label="Trades evaluated" value="Demo data" />
              <Metric label="Maximum drawdown" value="Awaiting verified history" placeholder={false} />
              <Metric label="Risk-gate rejection rate" value="Awaiting verified history" placeholder={false} />
            </div>
          </div>
        </section>

        {/* ── Trust & transparency ──────────────────────────────────────── */}
        <section className="landing-section">
          <div className="landing-container">
            <div className="landing-eyebrow">Trust &amp; Transparency</div>
            <h2 className="landing-h2">What the terminal always shows you</h2>
            <div className="landing-trust-list">
              <div className="landing-trust-item">
                <span className="landing-trust-mark">&rarr;</span>
                <span className="landing-cell-body">Every signal's source system, timeframe, and confidence — or an explicit "unknown" if the frontend can't verify it.</span>
              </div>
              <div className="landing-trust-item">
                <span className="landing-trust-mark">&rarr;</span>
                <span className="landing-cell-body">When two signals disagree for the same symbol, that disagreement is surfaced — never silently resolved.</span>
              </div>
              <div className="landing-trust-item">
                <span className="landing-trust-mark">&rarr;</span>
                <span className="landing-cell-body">Live vs. paper environment, broker connection, AUTOPILOT state, kill-switch state, and drawdown — visible from any screen in the terminal.</span>
              </div>
              <div className="landing-trust-item">
                <span className="landing-trust-mark">&rarr;</span>
                <span className="landing-cell-body">Unknown risk state is shown as unknown. It is never replaced with a default that looks safe.</span>
              </div>
              <div className="landing-trust-item">
                <span className="landing-trust-mark">&rarr;</span>
                <span className="landing-cell-body">Performance is only published once it is verified and clearly sourced — backtest, paper, and live results are never mixed.</span>
              </div>
              <div className="landing-trust-item">
                <span className="landing-trust-mark">&rarr;</span>
                <span className="landing-cell-body">Automation can be turned off at any time — Manual mode and the kill switch always take priority over Autopilot.</span>
              </div>
            </div>
          </div>
        </section>

        {/* ── Final CTA ─────────────────────────────────────────────────── */}
        <section className="landing-section" style={{ textAlign: "center" }}>
          <div className="landing-container">
            <h2 className="landing-h2">Start in paper. Prove the edge before it's live.</h2>
            <p className="landing-lede" style={{ margin: "0 auto 28px" }}>
              The terminal opens directly into paper trading — no live order can be placed until
              the account and environment are explicitly switched to live.
            </p>
            <Link className="landing-cta-btn" to="/terminal">Start Paper Trading</Link>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-container">
          <div className="landing-footer-row">
            <span className="landing-wordmark" style={{ fontSize: 15 }}>OLBOS</span>
            <div className="landing-footer-links">
              <span className="disabled" title="Not published">Privacy</span>
              <span className="disabled" title="Not published">Terms</span>
              <span className="disabled" title="Not published">Risk Disclosure</span>
              <span className="disabled" title="Not published">Contact</span>
              <Link to="/terminal">Sign In</Link>
              <span className="disabled" title="Not published">Company Info</span>
            </div>
          </div>
          <p className="landing-disclosure">
            Options and equity trading involves substantial risk of loss and is not suitable for
            all investors. OlbosTrade is currently in paper-trading evaluation with no verified
            live performance history. Nothing on this page is investment advice, and past or
            simulated results, once published, will not guarantee future returns.
          </p>
        </div>
      </footer>
    </div>
  );
}
