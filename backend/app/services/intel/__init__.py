"""Market News & Catalyst Intelligence Hub — provider abstraction and services.

Phase 1: data-provider abstraction, event calendar, smart watchlists,
data-quality envelope, and a deterministic "why is it moving?" assembler.

Design invariant: everything here is READ-ONLY research context. Nothing in
this package touches the order path, risk engine, guardrails, or kill switch.
News/filings are evidence for the existing workflow — never a trade trigger.
"""
