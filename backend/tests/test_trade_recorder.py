"""
Batch 3 — trade P&L correctness (TradeRecorder._gross_pnl).

Covers the equity P&L data-integrity fix: equity P&L must NOT use the ×100
options multiplier and must have the correct LONG sign (it previously inflated
~100× and inverted the sign because every row defaulted to instrument_type
"option"). Credit / debit spread signs are locked too.
"""

from __future__ import annotations

from app.services.trade_recorder import TradeRecorder


def test_equity_long_profit_no_100x():
    # Buy 100 sh @ $150, sell @ $160 → +$1,000 (NOT *100, NOT negative).
    pnl = TradeRecorder._gross_pnl(
        credit=150.0, cost_to_close=160.0, qty=100,
        is_equity=True, strategy="equity",
    )
    assert pnl == 1000.0


def test_equity_long_loss_sign():
    # Buy 100 sh @ $150, sell @ $145 → -$500.
    pnl = TradeRecorder._gross_pnl(
        credit=150.0, cost_to_close=145.0, qty=100,
        is_equity=True, strategy="equity",
    )
    assert pnl == -500.0


def test_credit_spread_keeps_100x():
    # Collect $1.50 credit/share, buy back @ $0.50 → (1.5-0.5)*1*100 = $100.
    pnl = TradeRecorder._gross_pnl(
        credit=1.50, cost_to_close=0.50, qty=1,
        is_equity=False, strategy="bull_put_spread",
    )
    assert pnl == 100.0


def test_debit_spread_sign_inverted():
    # Pay $2 debit, close @ $3 → profit (cost-credit)*100 = $100.
    pnl = TradeRecorder._gross_pnl(
        credit=2.0, cost_to_close=3.0, qty=1,
        is_equity=False, strategy="bull_call_debit_spread",
    )
    assert pnl == 100.0
