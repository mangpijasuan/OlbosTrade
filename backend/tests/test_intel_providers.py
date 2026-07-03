"""Tests for EDGAR / RSS / FRED providers. HTTP is mocked — no network calls."""

import httpx
import pytest

from app.services.intel.providers.edgar import EdgarProvider
from app.services.intel.providers.fred import FredProvider
from app.services.intel.providers.rss_news import RssNewsProvider
from app.services.intel.provider_base import QualityStatus


class _Resp:
    def __init__(self, text="", status=200, json_data=None):
        self.text = text
        self.status_code = status
        self._json = json_data or {}
    def json(self):
        return self._json


_EDGAR_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>8-K - Current report</title>
    <updated>2026-07-02T12:00:00-04:00</updated>
    <link href="https://sec.gov/x" />
    <category term="8-K"/>
  </entry>
  <entry>
    <title>4 - Statement of changes in beneficial ownership</title>
    <updated>2026-06-29T09:00:00-04:00</updated>
    <link href="https://sec.gov/y" />
    <category term="4"/>
  </entry>
</feed>"""

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>NVDA hits new high</title><link>http://n/1</link><pubDate>Wed, 02 Jul 2026 14:00:00 GMT</pubDate></item>
  <item><title>Chip demand strong</title><link>http://n/2</link><pubDate>Wed, 02 Jul 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_edgar_parses_and_flags_insider(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(_EDGAR_ATOM))
    items = EdgarProvider().fetch_filings("NVDA", limit=10)
    assert len(items) == 2
    forms = {i.payload["form_type"] for i in items}
    assert "8-K" in forms and "4" in forms
    form4 = next(i for i in items if i.payload["form_type"] == "4")
    assert form4.payload["is_insider"] is True
    assert form4.payload["category"] == "Insider"
    assert items[0].is_delayed is True


def test_edgar_fails_soft_on_bad_response(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp("not xml", status=500))
    assert EdgarProvider().fetch_filings("NVDA") == []


def test_edgar_health_never_raises():
    assert EdgarProvider().health().available is True


def test_rss_parses_headlines(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(_RSS))
    items = RssNewsProvider().fetch_news("NVDA", limit=10)
    assert len(items) == 2
    assert items[0].payload["title"] == "NVDA hits new high"
    assert items[0].source == "Public RSS news"


def test_rss_fails_soft(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", boom)
    assert RssNewsProvider().fetch_news("NVDA") == []


def test_fred_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    p = FredProvider()
    assert p.health().available is False
    env = p.fetch_series("CPIAUCSL")
    assert env.status == QualityStatus.UNAVAILABLE
    assert env.payload["value"] is None


def test_fred_reads_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test123")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(
        json_data={"observations": [{"value": "3.1", "date": "2026-06-01"}]}))
    p = FredProvider()
    assert p.health().available is True
    env = p.fetch_series("CPIAUCSL")
    assert env.payload["value"] == "3.1"
    assert env.status == QualityStatus.OK
