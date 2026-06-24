-- ═══════════════════════════════════════════════════════════════════════════════
-- OlbosQuant — reset trading / execution history
--
-- Wipes ALL recorded live trades, their journal entries, DB-tracked positions, and
-- the risk state that the guardrails rehydrate from (consecutive losses, cooling-off
-- / pause windows). Use this to start a clean slate — e.g. after the audit fixes,
-- so win rate / drawdown / P&L are computed only on trustworthy data.
--
-- What it does NOT touch:
--   • backtest_runs / market_snapshots / signal_scores  (backtest + ML history)
--   • options_flow                                       (options-intelligence data)
--   • broker positions at IBKR                           (this only clears OlbosQuant's
--                                                          DB — close real positions in
--                                                          IB Gateway yourself first)
--
-- Runs as a single transaction: either everything is cleared or nothing is.
-- Deletes are ordered so foreign keys (journal_entries → trades) are satisfied.
-- ═══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- journal_entries.trade_id references trades.id — delete children first
DELETE FROM journal_entries;
DELETE FROM trades;

-- DB-tracked positions (live position mirror)
DELETE FROM positions;

-- Guardrail / EmotionGuard state: consecutive_losses + cooling_off_until are read
-- from the most recent portfolio_snapshots row, so clear these too or a stale loss
-- streak / pause will carry into the next session.
DELETE FROM portfolio_snapshots;
DELETE FROM guardrail_events;

COMMIT;

-- Show the result
SELECT 'trades'              AS table, COUNT(*) AS remaining FROM trades
UNION ALL SELECT 'journal_entries',    COUNT(*) FROM journal_entries
UNION ALL SELECT 'positions',          COUNT(*) FROM positions
UNION ALL SELECT 'portfolio_snapshots',COUNT(*) FROM portfolio_snapshots
UNION ALL SELECT 'guardrail_events',   COUNT(*) FROM guardrail_events;
