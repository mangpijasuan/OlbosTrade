"""
IBKR Live Data WebSocket endpoint.
Manages subscriptions to live chain updates and broadcasts pricing data to connected clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Set
from datetime import datetime, timezone
from dataclasses import dataclass

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@dataclass
class LiveSubscription:
    """Represents an active subscription to a ticker or option chain."""
    key: str
    callbacks: Set[Callable] = None

    def __post_init__(self):
        if self.callbacks is None:
            self.callbacks = set()


class IBKRLiveDataBroker:
    """
    Central broker for managing WebSocket subscriptions and broadcasting live data.
    Simulates real-time updates; in production would connect to actual IBKR API.
    """

    def __init__(self):
        self.subscriptions: dict[str, Set[WebSocket]] = {}
        self.active_connections: Set[WebSocket] = set()
        self.update_task = None
        self.is_paused = False

    async def connect(self, websocket: WebSocket):
        """Register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"IBKR Live client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Unregister a WebSocket connection and clean up subscriptions."""
        self.active_connections.discard(websocket)
        # Remove from all subscriptions
        for subscribers in self.subscriptions.values():
            subscribers.discard(websocket)
        logger.info(f"IBKR Live client disconnected. Remaining connections: {len(self.active_connections)}")

    async def subscribe(self, websocket: WebSocket, key: str):
        """Subscribe a client to updates for a specific key (ticker or option chain)."""
        if key not in self.subscriptions:
            self.subscriptions[key] = set()
        self.subscriptions[key].add(websocket)
        logger.debug(f"Subscription added: {key} (subscribers: {len(self.subscriptions[key])})")

    def unsubscribe(self, websocket: WebSocket, key: str):
        """Unsubscribe a client from a specific key."""
        if key in self.subscriptions:
            self.subscriptions[key].discard(websocket)
            if not self.subscriptions[key]:
                del self.subscriptions[key]
            logger.debug(f"Subscription removed: {key}")

    async def broadcast(self, key: str, data: dict[str, Any]):
        """Broadcast an update to all subscribers of a key."""
        if key not in self.subscriptions:
            return

        disconnected = []
        for websocket in self.subscriptions[key]:
            try:
                await websocket.send_json(data)
            except Exception as exc:
                logger.debug(f"Failed to broadcast to subscriber: {exc}")
                disconnected.append(websocket)

        # Clean up disconnected clients
        for ws in disconnected:
            self.disconnect(ws)

    async def start_update_loop(self):
        """
        Simulate live data updates (30s interval for quotes, 2s for option chains).
        In production, this would connect to IBKR API streams.
        """
        logger.info("IBKR Live update loop started")
        tick = 0
        try:
            while True:
                await asyncio.sleep(2)

                if self.is_paused:
                    # Skip broadcasting while paused
                    continue

                tick += 1

                # Broadcast to all active subscriptions
                for key in list(self.subscriptions.keys()):
                    if not self.subscriptions[key]:
                        continue

                    data = self._simulate_update(key, tick)
                    if data:
                        await self.broadcast(key, data)

        except asyncio.CancelledError:
            logger.info("IBKR Live update loop stopped")
        except Exception as exc:
            logger.error(f"IBKR Live update loop error: {exc}")

    def pause(self) -> bool:
        """Pause live data updates. Returns True if state changed."""
        if not self.is_paused:
            self.is_paused = True
            logger.info("IBKR Live data paused (disconnecting from other devices)")
            return True
        return False

    def resume(self) -> bool:
        """Resume live data updates. Returns True if state changed."""
        if self.is_paused:
            self.is_paused = False
            logger.info("IBKR Live data resumed")
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        """Get current broker status."""
        return {
            "is_paused": self.is_paused,
            "active_connections": len(self.active_connections),
            "subscriptions": len(self.subscriptions),
            "subscription_keys": list(self.subscriptions.keys()),
        }

    def _simulate_update(self, key: str, tick: int) -> dict[str, Any] | None:
        """
        Simulate a live data update for testing.
        In production, this would fetch real data from IBKR API.
        """
        import random

        # Parse key: "TICKER" for equity, "TICKER:STRIKE:STRIKE:TYPE" for options
        parts = key.split(":")
        if len(parts) == 1:
            # Equity quote
            ticker = parts[0]
            base_price = self._get_base_price(ticker)
            price_change = random.uniform(-0.5, 0.5)
            return {
                "key": key,
                "ticker": ticker,
                "lastPrice": round(base_price + price_change, 2),
                "bid": round(base_price + price_change - 0.01, 2),
                "ask": round(base_price + price_change + 0.01, 2),
                "bidSize": random.randint(100, 1000),
                "askSize": random.randint(100, 1000),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        elif len(parts) == 4:
            # Option chain update
            ticker, short_strike, long_strike, option_type = parts
            short_strike, long_strike = float(short_strike), float(long_strike)

            # Simulate credit price changes
            base_credit = abs(short_strike - long_strike) * 0.3
            credit = round(base_credit + random.uniform(-0.05, 0.05), 2)

            return {
                "key": key,
                "ticker": ticker,
                "shortStrike": short_strike,
                "longStrike": long_strike,
                "optionType": option_type,
                "credit": credit,
                "iv": round(random.uniform(0.15, 0.35), 3),
                "delta": round(random.uniform(0.2, 0.8), 3),
                "gamma": round(random.uniform(0.01, 0.05), 4),
                "theta": round(random.uniform(-0.1, -0.01), 3),
                "vega": round(random.uniform(0.05, 0.15), 3),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return None

    def _get_base_price(self, ticker: str) -> float:
        """Return a base price for a ticker (for simulation)."""
        base_prices = {
            "SPY": 450.0,
            "ES": 5500.0,
            "QQQ": 400.0,
            "AAPL": 180.0,
            "MSFT": 380.0,
            "TSLA": 250.0,
        }
        return base_prices.get(ticker.upper(), 100.0)


# Global broker instance
_live_broker = IBKRLiveDataBroker()


@router.get("/live/status")
async def get_live_status() -> dict:
    """
    Get current status of IBKR live data broker.

    Returns:
    - is_paused: Whether live data updates are paused
    - active_connections: Number of active WebSocket clients
    - subscriptions: Number of active subscriptions (ticker/chain keys)
    - subscription_keys: List of all subscription keys
    """
    return _live_broker.get_status()


@router.post("/live/pause")
async def pause_live_data() -> dict:
    """
    Pause live data updates.
    Use this when you need to login to IBKR on another device.
    WebSocket clients remain connected but won't receive updates.

    Returns:
    - paused: Whether pause was successful (true if state changed, false if already paused)
    - message: Status message
    """
    was_paused = _live_broker.is_paused
    _live_broker.pause()
    return {
        "paused": True,
        "message": "IBKR live data paused — you can now login on other devices" if not was_paused else "Already paused"
    }


@router.post("/live/resume")
async def resume_live_data() -> dict:
    """
    Resume live data updates after pausing.
    WebSocket clients will receive live updates again.

    Returns:
    - resumed: Whether resume was successful (true if state changed, false if already running)
    - message: Status message
    """
    was_paused = _live_broker.is_paused
    _live_broker.resume()
    return {
        "resumed": True,
        "message": "IBKR live data resumed" if was_paused else "Already running"
    }


@router.websocket("/live")
async def websocket_live_data(websocket: WebSocket):
    """
    WebSocket endpoint for real-time IBKR live data.

    Clients connect and send JSON messages:
    - Subscribe: {"action": "subscribe", "key": "TICKER" or "TICKER:SHORT:LONG:TYPE"}
    - Unsubscribe: {"action": "unsubscribe", "key": "..."}
    - Ping: {"action": "ping"}

    Server broadcasts updates as JSON:
    - For equity: {key, ticker, lastPrice, bid, ask, bidSize, askSize, timestamp}
    - For options: {key, ticker, shortStrike, longStrike, optionType, credit, iv, delta, gamma, theta, vega, timestamp}
    """
    await _live_broker.connect(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                logger.debug(f"Invalid JSON received: {data}")
                continue

            action = msg.get("action", "").lower()
            key = msg.get("key", "").upper()

            if action == "subscribe" and key:
                await _live_broker.subscribe(websocket, key)
                logger.debug(f"Client subscribed to {key}")

            elif action == "unsubscribe" and key:
                _live_broker.unsubscribe(websocket, key)
                logger.debug(f"Client unsubscribed from {key}")

            elif action == "ping":
                try:
                    await websocket.send_json({"action": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
                except Exception:
                    pass

            else:
                logger.debug(f"Unknown action: {action}")

    except WebSocketDisconnect:
        _live_broker.disconnect(websocket)
    except Exception as exc:
        logger.error(f"WebSocket error: {exc}")
        _live_broker.disconnect(websocket)


async def startup_ibkr_live():
    """Called on app startup to initialize the live data broker."""
    global _live_broker
    if _live_broker.update_task is None:
        _live_broker.update_task = asyncio.create_task(_live_broker.start_update_loop())
        logger.info("IBKR Live data broker initialized")


async def shutdown_ibkr_live():
    """Called on app shutdown to clean up the live data broker."""
    global _live_broker
    if _live_broker.update_task:
        _live_broker.update_task.cancel()
        try:
            await _live_broker.update_task
        except asyncio.CancelledError:
            pass
        logger.info("IBKR Live data broker shut down")
