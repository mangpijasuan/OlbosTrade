"""
Insider & Filing Intelligence — Module 8.

Summarises SEC Form 3/4/5 activity for a symbol from EDGAR filings: recent
insider-filing count, cluster detection, and recency. It treats this strictly
as RESEARCH CONTEXT, not an automatic trade signal.

Honesty about the data: the EDGAR index/Atom feed gives filing type + date, but
NOT transaction direction (buy vs sell) or share amounts — those require parsing
each Form 4 XML. This module surfaces that limitation rather than inventing a
buy/sell narrative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class InsiderSummary:
    symbol: str
    insider_filings: int
    cluster: bool                       # several insider filings in a short window
    most_recent: str | None
    context: str
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "insider_filings": self.insider_filings,
            "cluster": self.cluster,
            "most_recent": self.most_recent,
            "context": self.context,
            "limitations": self.limitations,
            "research_only": True,      # never an automatic trade signal
        }


def summarize_insider(symbol: str, filings: list[dict], cluster_window_days: int = 14,
                      cluster_min: int = 3) -> InsiderSummary:
    """filings: list of enveloped EDGAR items (each with payload.form_type,
    payload.is_insider, and top-level as_of)."""
    now = datetime.now(timezone.utc)
    insider = []
    for f in filings:
        payload = f.get("payload", f)
        if payload.get("is_insider") or payload.get("form_type") in ("3", "4", "5", "3/A", "4/A", "5/A"):
            insider.append(f)

    # Recency-window cluster.
    recent = 0
    most_recent = None
    for f in insider:
        as_of = f.get("as_of")
        if as_of:
            try:
                dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                if most_recent is None or as_of > most_recent:
                    most_recent = as_of
                if (now - dt).days <= cluster_window_days:
                    recent += 1
            except Exception:
                continue

    cluster = recent >= cluster_min
    if not insider:
        context = "No recent insider (Form 3/4/5) filings found."
    elif cluster:
        context = f"Cluster: {recent} insider filings in the last {cluster_window_days} days — worth reviewing."
    else:
        context = f"{len(insider)} recent insider filing(s); no cluster."

    return InsiderSummary(
        symbol=symbol,
        insider_filings=len(insider),
        cluster=cluster,
        most_recent=most_recent[:10] if most_recent else None,
        context=context,
        limitations=[
            "Form 4 direction (buy vs sell) and share amounts require parsing each "
            "filing — not available from the index feed.",
            "Insider filings can be delayed and do not guarantee price movement.",
        ],
    )
