"""
RSS news provider (free, no API key).

Pulls per-symbol headlines from a public RSS feed and envelopes them. Only the
sourced item (title, link, published, source) is surfaced — the classification
layer (Phase 3) never invents content, and this provider never asserts a cause.

Fail-soft: any network/parse error yields an empty list; health never raises.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.services.intel.provider_base import (
    DataEnvelope, NewsProvider, ProviderHealth, QualityStatus, make_envelope,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Yahoo Finance headline RSS — free, per-symbol, delayed. Overridable via env.
_FEED_TMPL = os.environ.get(
    "NEWS_RSS_TEMPLATE",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
)


class RssNewsProvider(NewsProvider):
    name = "Public RSS news"

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, available=True, detail="delayed public RSS")

    def fetch_news(self, symbol: str, limit: int = 20) -> list[DataEnvelope[dict]]:
        url = _FEED_TMPL.format(symbol=symbol)
        try:
            r = httpx.get(url, headers={"User-Agent": "OlbosQuant/1.0"}, timeout=6.0,
                          follow_redirects=True)
            if r.status_code != 200 or not r.text.strip().startswith("<"):
                return []
            root = ET.fromstring(r.text)
        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", symbol, exc)
            return []

        out: list[DataEnvelope[dict]] = []
        for item in root.iter("item"):
            title = _text(item, "title")
            link = _text(item, "link")
            pub = _text(item, "pubDate")
            if not title:
                continue
            out.append(make_envelope(
                {"title": title, "link": link, "published": pub},
                source=self.name,
                as_of=_parse_dt(pub),
                confidence=0.6,      # headline exists; relevance/impact not judged here
                status=QualityStatus.OK,
                is_delayed=True,
                limitations=["Headline only — relevance and impact are not assessed by this provider"],
            ))
            if len(out) >= limit:
                break
        return out


def _text(item: ET.Element, tag: str) -> str:
    el = item.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _parse_dt(s: str) -> datetime:
    try:
        return parsedate_to_datetime(s) if s else datetime.now(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)
