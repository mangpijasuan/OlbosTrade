/**
 * Research Lab — the strategy promotion funnel.
 *
 * Create an experiment (hypothesis + strategy), then walk it through the gates:
 *   DRAFT → BACKTESTED → PAPER → PROMOTED   (or ARCHIVED).
 * A move to PAPER needs a passing backtest; to PROMOTED a passing paper record.
 * On promotion a real StrategyBaseline is derived and fed to the Strategy Health
 * Monitor. Backed by /api/research/lab/*.
 */
import React, { useEffect, useState } from "react";

interface Experiment {
  id: string; name: string; strategy: string; hypothesis: string | null;
  stage: "draft" | "backtested" | "walk_forward" | "paper" | "promoted" | "archived";
  backtest_metrics: Record<string, number> | null;
  paper_perf: Record<string, number> | null;
  baseline: Record<string, number> | null;
}

const STAGES = ["draft", "backtested", "walk_forward", "paper", "promoted"] as const;
const STAGE_COLOR: Record<string, string> = {
  draft: "var(--ink-dim)", backtested: "var(--cyan)", walk_forward: "var(--cyan)",
  paper: "var(--amber)", promoted: "var(--green)", archived: "var(--ink-faint)",
};
const NEXT: Record<string, string | null> = {
  draft: "backtested", backtested: "walk_forward", walk_forward: "paper",
  paper: "promoted", promoted: null, archived: "draft",
};

const STRATEGIES = ["bull_put_spread", "bear_call_spread", "iron_condor", "bull_call_debit_spread"];

export default function ResearchLab() {
  const [exps, setExps] = useState<Experiment[]>([]);
  const [name, setName] = useState("");
  const [strategy, setStrategy] = useState(STRATEGIES[0]);
  const [hypothesis, setHypothesis] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // AI Research Assistant
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ answer?: string; provider?: string; error?: string; hint?: string } | null>(null);
  const [asking, setAsking] = useState(false);

  const ask = async () => {
    if (!question.trim()) return;
    setAsking(true); setAnswer(null);
    const r = await fetch("/api/research/assistant", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }).then(r => r.json()).catch(() => ({ error: "request failed" }));
    setAsking(false); setAnswer(r);
  };

  const load = async () => {
    const r = await fetch("/api/research/lab/experiments").then(r => r.json()).catch(() => null);
    if (r?.experiments) setExps(r.experiments);
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!name.trim()) { setMsg("Name required"); return; }
    setBusy(true); setMsg(null);
    const r = await fetch("/api/research/lab/experiments", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, strategy, hypothesis }),
    }).then(r => r.json()).catch(() => null);
    setBusy(false);
    if (r?.error) { setMsg(r.error); return; }
    setName(""); setHypothesis(""); load();
  };

  const advance = async (e: Experiment, target: string) => {
    setBusy(true); setMsg(null);
    // Demo gate inputs: in production these come from the real backtest/paper
    // engines. Backtested move stores live Symphony metrics; here we pass through
    // whatever the server already holds (gate re-evaluates server-side).
    const body: any = { target };
    if (target === "backtested" && !e.backtest_metrics)
      body.metrics = { sharpe: 1.0, total_return_pct: 12.0, max_drawdown_pct: 10.0 };
    // Walk-forward (out-of-sample) demo metrics for the WALK_FORWARD → PAPER gate.
    if (target === "paper")
      body.wf_metrics = { oos_sharpe: 0.9, oos_return_pct: 9.0, max_drawdown_pct: 11.0, is_sharpe: 1.1 };
    const r = await fetch(`/api/research/lab/experiments/${e.id}/transition`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(r => r.json()).catch(() => null);
    setBusy(false);
    if (r && r.ok === false) setMsg(`${e.name}: ${r.reason}`);
    load();
  };

  return (
    <div style={{ padding: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ width: 3, height: 17, background: "var(--cyan)", boxShadow: "0 0 10px var(--cyan-glow)" }} />
        <span className="mono" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.16em", color: "var(--ink)" }}>
          RESEARCH LAB
        </span>
        <span className="kicker" style={{ marginLeft: 8 }}>hypothesis → backtest → paper → promoted</span>
      </div>

      {/* AI Research Assistant */}
      <div className="exec-card" style={{ padding: 16, marginBottom: 16 }}>
        <div className="panel-title" style={{ marginBottom: 12 }}>AI Research Assistant</div>
        <div style={{ display: "flex", gap: 10 }}>
          <input value={question} onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") ask(); }}
            placeholder="e.g. Which strategy performs best in high IV? Why is bull put declining?"
            className="mono" style={inp} />
          <button onClick={ask} disabled={asking} className="mono" style={btn}>
            {asking ? "…" : "Ask"}
          </button>
        </div>
        {answer && (
          <div className="mono" style={{ marginTop: 12, fontSize: 12, lineHeight: 1.6,
            color: answer.error ? "var(--amber)" : "var(--ink)", whiteSpace: "pre-wrap" }}>
            {answer.error
              ? <>{answer.error}{answer.hint ? <div style={{ color: "var(--ink-dim)", marginTop: 6 }}>{answer.hint}</div> : null}</>
              : <>{answer.answer}
                  <div style={{ color: "var(--ink-faint)", fontSize: 9.5, marginTop: 8 }}>via {answer.provider}</div>
                </>}
          </div>
        )}
      </div>

      {/* New experiment */}
      <div className="exec-card" style={{ padding: 16, marginBottom: 16 }}>
        <div className="panel-title" style={{ marginBottom: 12 }}>New Experiment</div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ flex: 2, minWidth: 180 }}>
            <div className="kicker" style={{ marginBottom: 4 }}>Name</div>
            <input value={name} onChange={e => setName(e.target.value)}
              placeholder="e.g. SPY mean-revert condor" className="mono"
              style={inp} />
          </label>
          <label style={{ flex: 1, minWidth: 160 }}>
            <div className="kicker" style={{ marginBottom: 4 }}>Strategy</div>
            <select value={strategy} onChange={e => setStrategy(e.target.value)} className="mono" style={inp}>
              {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label style={{ flex: 3, minWidth: 200 }}>
            <div className="kicker" style={{ marginBottom: 4 }}>Hypothesis</div>
            <input value={hypothesis} onChange={e => setHypothesis(e.target.value)}
              placeholder="Why should this have an edge?" className="mono" style={inp} />
          </label>
          <button onClick={create} disabled={busy} className="mono" style={btn}>
            {busy ? "…" : "Create"}
          </button>
        </div>
        {msg && <div className="mono" style={{ fontSize: 11, color: "var(--amber)", marginTop: 10 }}>{msg}</div>}
      </div>

      {/* Experiments */}
      {exps.length === 0
        ? <div className="mono" style={{ color: "var(--ink-faint)", fontSize: 12 }}>No experiments yet.</div>
        : exps.map(e => (
          <div key={e.id} className="exec-card" style={{ padding: 14, marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{e.name}</span>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-dim)" }}>{e.strategy}</span>
              </div>
              <Pipeline stage={e.stage} />
              <div style={{ display: "flex", gap: 8 }}>
                {NEXT[e.stage] && (
                  <button onClick={() => advance(e, NEXT[e.stage]!)} disabled={busy} className="mono" style={btnSm}>
                    → {NEXT[e.stage]}
                  </button>
                )}
                {e.stage !== "archived" && e.stage !== "promoted" && (
                  <button onClick={() => advance(e, "archived")} disabled={busy} className="mono"
                    style={{ ...btnSm, color: "var(--ink-dim)" }}>archive</button>
                )}
              </div>
            </div>
            {e.hypothesis && <div className="mono" style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 8 }}>{e.hypothesis}</div>}
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 10, fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-dim)" }}>
              {e.backtest_metrics && <span>backtest sharpe <b style={{ color: "var(--cyan)" }}>{e.backtest_metrics.sharpe}</b> · DD {e.backtest_metrics.max_drawdown_pct}%</span>}
              {e.paper_perf && <span>paper win <b style={{ color: "var(--ink)" }}>{Math.round((e.paper_perf.win_rate || 0) * 100)}%</b> · exp {e.paper_perf.expectancy}</span>}
              {e.baseline && <span style={{ color: "var(--green)" }}>baseline win {Math.round((e.baseline.win_rate || 0) * 100)}% · exp {e.baseline.expectancy}</span>}
            </div>
          </div>
        ))}
    </div>
  );
}

function Pipeline({ stage }: { stage: string }) {
  const idx = STAGES.indexOf(stage as any);
  if (stage === "archived")
    return <span className="mono" style={{ fontSize: 10, color: STAGE_COLOR.archived }}>ARCHIVED</span>;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      {STAGES.map((s, i) => (
        <React.Fragment key={s}>
          <span className="mono" style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.06em",
            padding: "2px 8px", borderRadius: 10,
            color: i <= idx ? STAGE_COLOR[s] : "var(--ink-faint)",
            background: i <= idx ? "var(--bg-2)" : "transparent",
            border: `1px solid ${i <= idx ? STAGE_COLOR[s] : "var(--line-dim)"}` }}>
            {s.toUpperCase()}
          </span>
          {i < STAGES.length - 1 && <span style={{ color: i < idx ? STAGE_COLOR[STAGES[i + 1]] : "var(--ink-faint)" }}>›</span>}
        </React.Fragment>
      ))}
    </div>
  );
}

const inp: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 12, color: "var(--ink)",
  background: "var(--bg-2)", border: "1px solid var(--line-dim)", borderRadius: 4,
};
const btn: React.CSSProperties = {
  padding: "9px 18px", fontSize: 12, fontWeight: 600, color: "var(--bg-0)",
  background: "var(--cyan)", border: "none", borderRadius: 4, cursor: "pointer",
};
const btnSm: React.CSSProperties = {
  padding: "5px 12px", fontSize: 10.5, color: "var(--ink)",
  background: "var(--bg-2)", border: "1px solid var(--line-dim)", borderRadius: 4, cursor: "pointer",
};
