"""
SEC EDGAR filing provider (free, no API key).

Fetches a company's recent filings from EDGAR's public Atom feed and classifies
them, flagging Form 3/4/5 as insider filings. SEC requires a descriptive
User-Agent; requests are short-timeout and fail soft (empty list, never raise).

Data is public and delayed — envelopes are marked is_delayed=True and note the
EDGAR filing delay so the UI never implies real-time coverage.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from app.services.intel.provider_base import (
    DataEnvelope, FilingProvider, ProviderHealth, QualityStatus, make_envelope,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
_UA = os.environ.get("SEC_USER_AGENT", "OlbosQuant research (contact: ops@olbosquant.local)")
_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"

_INSIDER_FORMS = {"3", "4", "5", "3/A", "4/A", "5/A"}


class EdgarProvider(FilingProvider):
    name = "SEC EDGAR"

    def health(self) -> ProviderHealth:
        # EDGAR needs no key; consider it available unless the network is down.
        # A cheap check keeps this from making a request on every health poll.
        return ProviderHealth(self.name, available=True, detail="public Atom feed")

    def fetch_filings(self, symbol: str, limit: int = 20) -> list[DataEnvelope[dict]]:
        params = {
            "action": "getcompany", "ticker": symbol, "type": "",
            "dateb": "", "owner": "include", "count": str(limit), "output": "atom",
        }
        try:
            r = httpx.get(_BASE, params=params, headers={"User-Agent": _UA}, timeout=6.0)
            if r.status_code != 200 or not r.text.strip().startswith("<"):
                return []
            root = ET.fromstring(r.text)
        except Exception as exc:
            logger.warning("EDGAR fetch failed for %s: %s", symbol, exc)
            return []

        out: list[DataEnvelope[dict]] = []
        for entry in root.findall("a:entry", _ATOM_NS):
            title = _text(entry, "a:title")
            updated = _text(entry, "a:updated")
            link_el = entry.find("a:link", _ATOM_NS)
            link = link_el.get("href") if link_el is not None else None
            form_type = _text(entry, "a:category") or _form_from_title(title)
            as_of = _parse_dt(updated)
            is_insider = form_type in _INSIDER_FORMS
            out.append(make_envelope(
                {
                    "form_type": form_type,
                    "title": title,
                    "link": link,
                    "is_insider": is_insider,
                    "category": "Insider" if is_insider else "Filing",
                },
                source=self.name,
                as_of=as_of,
                confidence=0.9,      # filings are authoritative, just delayed
                status=QualityStatus.OK,
                is_delayed=True,
                limitations=["EDGAR filings can post with a delay after the event"],
            ))
            if len(out) >= limit:
                break
        return out


def _text(entry: ET.Element, path: str) -> str:
    el = entry.find(path, _ATOM_NS)
    if el is not None and el.get("term"):
        return el.get("term") or ""
    return (el.text or "").strip() if el is not None else ""


def _form_from_title(title: str) -> str:
    # EDGAR titles look like "4 - Statement of changes in beneficial ownership".
    return title.split(" - ", 1)[0].strip() if title else ""


def _parse_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
