"""
Crypto Short-Term Maker MM
==========================
Targets BTC/ETH/SOL short-expiry binary markets (≤4h to resolution).
Strategy: when YES_ask + NO_ask < $0.995, buy both sides.
At resolution, exactly one side pays $1 → guaranteed profit = $1 - combined_cost.
Capital: 30% of NAV per trade (short duration = low holding risk), hard-capped at $30.

This is a focused, higher-capital version of intra_arb that only runs on
crypto directional markets where fill rates are highest.

Documented performance: $70K total profit reported by a similar bot.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from app.models import StrategyName, TradeType, PositionStatus
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    CRYPTO_MM_SCAN_INTERVAL, CRYPTO_MM_MIN_EDGE,
    CRYPTO_MM_POSITION_PCT, CRYPTO_MM_MAX_CAPITAL_USD,
    CRYPTO_MM_MAX_EXPIRY_HOURS,
)

log = logging.getLogger("strategy.crypto_mm")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_opportunities_this_session = 0
_recently_traded: Dict[str, float] = {}
TRADE_COOLDOWN_SEC = 120.0

# Crypto asset keywords
_CRYPTO_KEYWORDS = [
    "btc", "bitcoin", "eth", "ethereum", "sol", "solana",
    "bnb", "xrp", "doge", "matic", "avax", "ada", "link",
    "crypto price", "will crypto",
]

# Short time-horizon phrases in question text
_SHORT_HORIZON_PHRASES = [
    "1 min", "2 min", "3 min", "5 min", "10 min", "15 min",
    "30 min", "1 hour", "2 hour", "3 hour",
    "1-minute", "5-minute", "15-minute",
    "next hour", "this hour", "by end of hour",
]


def _is_target_market(m) -> bool:
    """True if this is a short-horizon crypto binary market."""
    q = m.question.lower()

    has_crypto = any(kw in q for kw in _CRYPTO_KEYWORDS)
    if not has_crypto:
        return False

    # Accept via explicit short-horizon phrasing
    if any(ph in q for ph in _SHORT_HORIZON_PHRASES):
        return True

    # Or accept via end_date proximity
    if m.end_date:
        try:
            now = datetime.now(timezone.utc)
            end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
            hours_remaining = (end - now).total_seconds() / 3600.0
            return 0.01 < hours_remaining <= CRYPTO_MM_MAX_EXPIRY_HOURS
        except Exception:
            pass

    return False


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
        "opportunities_this_session": _opportunities_this_session,
        "scan_interval_sec": CRYPTO_MM_SCAN_INTERVAL,
        "min_edge": CRYPTO_MM_MIN_EDGE,
    }


def stop():
    global _running
    _running = False


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


async def scan_once(wallet: PaperWallet):
    global _last_scan, _scan_count, _opportunities_this_session

    markets = md.get_markets()
    if not markets:
        return

    _last_scan = datetime.utcnow()
    _scan_count += 1
    wallet.last_scan = _last_scan
    wallet.status = "scanning"

    now_ts = time.time()

    candidates = []
    for m in markets.values():
        if now_ts - _recently_traded.get(m.id, 0) < TRADE_COOLDOWN_SEC:
            continue
        if not _is_target_market(m):
            continue
        # Need live CLOB prices on both sides
        if not (0 < m.yes_best_ask < 1 and 0 < m.no_best_ask < 1
                and m.yes_best_bid > 0 and m.no_best_bid > 0):
            continue
        # Sanity check
        if m.yes_best_bid >= m.yes_best_ask or m.no_best_bid >= m.no_best_ask:
            continue

        combined_ask = m.yes_best_ask + m.no_best_ask
        edge = 1.0 - combined_ask
        if edge < CRYPTO_MM_MIN_EDGE:
            continue

        candidates.append((m, combined_ask, edge))

    # Sort by edge descending
    candidates.sort(key=lambda x: x[2], reverse=True)

    log.info(
        f"[crypto_mm] Scan #{_scan_count}: {len(markets)} markets → "
        f"{len(candidates)} crypto arb opportunities"
    )

    for market, combined_ask, edge in candidates[:5]:
        if wallet.cash < 2.0:
            break

        # Size: 30% of NAV up to hard cap — short positions expire in ≤4h
        max_spend = min(
            wallet.nav * CRYPTO_MM_POSITION_PCT,
            CRYPTO_MM_MAX_CAPITAL_USD,
            wallet.cash * 0.9,
        )
        if max_spend < 1.0:
            continue

        # Number of "units" we buy — each unit costs combined_ask, pays $1 at resolution
        units = round(max_spend / combined_ask, 4)
        cost = round(units * combined_ask, 4)
        net_profit = round(units * edge, 5)

        if net_profit <= 0:
            continue

        notes = (
            f"CryptoMM: yes_ask={market.yes_best_ask:.4f} no_ask={market.no_best_ask:.4f} "
            f"combined={combined_ask:.4f} edge={edge:.4f} exp_pnl=${net_profit:.4f}"
        )

        pos = await wallet.open_position(
            market_id=market.id,
            market_question=market.question,
            direction=f"BUY_BOTH yes={market.yes_best_ask:.3f}+no={market.no_best_ask:.3f}",
            cost=cost,
            size=units,
            trade_type=TradeType.BUY_BOTH,
            price=combined_ask,
            notes=notes,
            resolution_time=market.end_date,
        )

        if pos:
            # For paper trading: lock in the profit immediately (arb is risk-free)
            close_price = round(combined_ask + edge, 4)
            await wallet.close_position(
                pos_id=pos.id,
                pnl=net_profit,
                close_price=close_price,
                trade_type=TradeType.CLOSE,
                notes=f"CryptoMM locked ${net_profit:.5f} on ${cost:.2f} | edge={edge:.4f}",
            )
            _recently_traded[market.id] = now_ts
            _opportunities_this_session += 1
            log.info(
                f"[crypto_mm] ✅ BUY_BOTH ${net_profit:.5f} | "
                f"combined={combined_ask:.4f} edge={edge:.4f} | "
                f"{market.question[:65]}"
            )

    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(
        f"[crypto_mm] Strategy started. "
        f"Min edge={CRYPTO_MM_MIN_EDGE}, interval={CRYPTO_MM_SCAN_INTERVAL}s, "
        f"max_expiry={CRYPTO_MM_MAX_EXPIRY_HOURS}h"
    )

    # Allow market data to load first
    await asyncio.sleep(10)

    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[crypto_mm] Scan error: {e}", exc_info=True)
        await asyncio.sleep(CRYPTO_MM_SCAN_INTERVAL)
