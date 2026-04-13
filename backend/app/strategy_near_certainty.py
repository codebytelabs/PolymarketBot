"""
Near-Certainty Conviction Bot
==============================
Finds markets priced at YES ask 82-96¢ (high crowd consensus = YES very likely).
Buys YES and holds until bid hits 97¢+ or market nears expiry (simulated resolution).

Why this works in paper trading:
  - Markets priced at 90¢ YES should resolve YES ~90% of the time
  - The 10¢ discount is time-value / uncertainty premium
  - As the event approaches certainty, price drifts 90¢ → 97¢ → 99¢ → $1
  - We capture the drift, not just the resolution

Generates CONTINUOUS activity because:
  - There are always 10-30 markets in the 82-96¢ band at any time
  - Positions open and close on a rolling basis (days-long holds)
  - Auto-closes when bid crosses 97¢ OR within 2h of expiry

Capital: 5% NAV per position, hard-capped at $6. Up to 10 concurrent positions.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

from app.models import StrategyName, TradeType, PositionStatus
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    NC_SCAN_INTERVAL, NC_MIN_YES_PRICE, NC_MAX_YES_PRICE,
    NC_CLOSE_THRESHOLD, NC_MAX_POSITIONS, NC_POSITION_PCT,
    NC_MAX_CAPITAL_USD, NC_MIN_VOLUME,
)

log = logging.getLogger("strategy.near_certainty")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_opportunities_this_session = 0
_open_market_ids: Set[str] = set()      # markets we currently hold
_recently_closed: Dict[str, float] = {} # market_id → timestamp, avoid re-entry
REENTRY_COOLDOWN_SEC = 3600.0           # 1h before re-entering same market


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
        "opportunities_this_session": _opportunities_this_session,
        "scan_interval_sec": NC_SCAN_INTERVAL,
        "min_yes_price": NC_MIN_YES_PRICE,
        "max_yes_price": NC_MAX_YES_PRICE,
        "close_threshold": NC_CLOSE_THRESHOLD,
    }


def stop():
    global _running
    _running = False


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


async def _try_close_positions(wallet: PaperWallet):
    """Close positions where YES bid has risen to threshold or market expires soon."""
    markets = md.get_markets()
    now = datetime.now(timezone.utc)

    for pos in list(wallet.open_positions):
        if pos.strategy != StrategyName.NEAR_CERTAIN:
            continue

        market = markets.get(pos.market_id)
        if not market:
            continue

        yes_bid = market.yes_best_bid
        close_reason = None
        close_price = yes_bid

        # Primary exit: price drifted up to threshold
        if yes_bid >= NC_CLOSE_THRESHOLD:
            close_reason = f"price_target yes_bid={yes_bid:.3f}"
            close_price = yes_bid

        # Secondary exit: within 2h of expiry → simulate resolution
        elif market.end_date:
            end = market.end_date if market.end_date.tzinfo else market.end_date.replace(tzinfo=timezone.utc)
            hours_remaining = (end - now).total_seconds() / 3600.0
            if hours_remaining <= 2.0:
                # At near-expiry, assume high-prob market resolves YES at $1
                if yes_bid > 0.90:
                    close_price = min(yes_bid, 0.98)
                    close_reason = f"near_expiry {hours_remaining:.1f}h yes_bid={yes_bid:.3f}"
                elif yes_bid < 0.30:
                    # Market flipped — resolved NO, close at loss
                    close_price = yes_bid if yes_bid > 0 else 0.02
                    close_reason = f"resolved_no {hours_remaining:.1f}h yes_bid={yes_bid:.3f}"

        # Tertiary: stale position > 14 days (market data disappeared / resolved)
        elif (now - pos.open_time.replace(tzinfo=timezone.utc)).days > 14:
            close_price = yes_bid if yes_bid > 0 else 0.5
            close_reason = f"stale_14d yes_bid={yes_bid:.3f}"

        if not close_reason:
            continue

        pnl = round((close_price - pos.cost_basis / pos.size) * pos.size, 5)
        await wallet.close_position(
            pos_id=pos.id,
            pnl=pnl,
            close_price=close_price,
            trade_type=TradeType.SELL_YES,
            notes=f"NC close: {close_reason} pnl=${pnl:.5f}",
        )
        _open_market_ids.discard(pos.market_id)
        _recently_closed[pos.market_id] = time.time()
        log.info(
            f"[near_certain] ✅ CLOSE {close_reason} | "
            f"pnl=${pnl:.5f} | {market.question[:60]}"
        )


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
    now_utc = datetime.now(timezone.utc)

    # First, try to close profitable / expiring positions
    await _try_close_positions(wallet)

    # Check how many open positions we already have
    open_count = len([p for p in wallet.open_positions if p.strategy == StrategyName.NEAR_CERTAIN])
    slots_available = NC_MAX_POSITIONS - open_count

    if slots_available <= 0:
        wallet.status = "idle"
        return

    candidates: List = []
    for m in markets.values():
        # Skip markets we already hold
        if m.id in _open_market_ids:
            continue
        # Skip recently closed
        if now_ts - _recently_closed.get(m.id, 0) < REENTRY_COOLDOWN_SEC:
            continue
        # Require meaningful volume
        if m.volume < NC_MIN_VOLUME:
            continue
        # Need a live YES ask in the target band
        yes_ask = m.yes_best_ask
        if not (NC_MIN_YES_PRICE <= yes_ask <= NC_MAX_YES_PRICE):
            continue
        # Need a live YES bid (ensures real order book depth)
        if m.yes_best_bid <= 0 or m.yes_best_bid >= yes_ask:
            continue
        # Only enter if expiry is 1h–48h away — short, resolvable windows
        if m.end_date:
            end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
            hrs = (end - now_utc).total_seconds() / 3600.0
            if hrs < 1.0 or hrs > 48.0:
                continue
        else:
            continue  # no expiry data → skip

        expected_return = (1.0 - yes_ask) / yes_ask  # % return if resolves YES at $1
        candidates.append((m, yes_ask, expected_return))

    # Sort by highest ask (most certain = highest price) — safer bets first
    candidates.sort(key=lambda x: x[1], reverse=True)

    log.info(
        f"[near_certain] Scan #{_scan_count}: {len(markets)} markets → "
        f"{len(candidates)} high-conviction candidates (slots={slots_available})"
    )

    entered = 0
    for market, yes_ask, exp_ret in candidates[:slots_available]:
        if wallet.cash < 1.0:
            break

        cost = min(
            wallet.nav * NC_POSITION_PCT,
            NC_MAX_CAPITAL_USD,
            wallet.cash * 0.9,
        )
        if cost < 0.50:
            continue

        size = round(cost / yes_ask, 4)
        notes = (
            f"NC: yes_ask={yes_ask:.4f} exp_ret={exp_ret:.3%} "
            f"vol=${market.volume:.0f}"
        )

        pos = await wallet.open_position(
            market_id=market.id,
            market_question=market.question,
            direction=f"BUY_YES @ {yes_ask:.3f}",
            cost=round(cost, 4),
            size=size,
            trade_type=TradeType.BUY_YES,
            price=yes_ask,
            notes=notes,
            resolution_time=market.end_date,
        )

        if pos:
            _open_market_ids.add(market.id)
            _opportunities_this_session += 1
            entered += 1
            log.info(
                f"[near_certain] 🎯 BUY_YES ask={yes_ask:.3f} "
                f"exp_ret={exp_ret:.2%} cost=${cost:.2f} | "
                f"{market.question[:65]}"
            )

    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(
        f"[near_certain] Strategy started. "
        f"Band={NC_MIN_YES_PRICE:.2f}-{NC_MAX_YES_PRICE:.2f} "
        f"close_at={NC_CLOSE_THRESHOLD:.2f} max_pos={NC_MAX_POSITIONS}"
    )

    # Sync open positions on restart
    for pos in wallet.open_positions:
        if pos.strategy == StrategyName.NEAR_CERTAIN:
            _open_market_ids.add(pos.market_id)

    # Allow market data to load first
    await asyncio.sleep(12)

    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[near_certain] Scan error: {e}", exc_info=True)
        await asyncio.sleep(NC_SCAN_INTERVAL)
