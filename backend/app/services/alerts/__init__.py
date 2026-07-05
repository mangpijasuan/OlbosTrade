"""
Smart Alerts — rules-based, mode-aware, and SAFE by construction.

Alerts are informational or produce CANDIDATES only. An alert, webhook, chart
signal, or scanner event may NEVER submit a broker order. Autopilot candidates
must still pass the macro/event gate, Risk Engine, Portfolio Engine, execution
controls, and strategy eligibility — the alert engine cannot bypass any of them.

This package holds the pure rule-evaluation engine and mode routing; the order
path is never imported here.
"""
