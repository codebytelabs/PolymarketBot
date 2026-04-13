"""
Convergence Strategy
====================
The #1 proven Polymarket strategy: identify outcomes the market considers
near-certain, buy the winning side, and collect $1 at resolution.

Research basis:
- Top wallets execute 1,500+ trades generating $500K+ returns
- Convergence trading (0.90-0.99 → $1.00) is the most reliably profitable
- Key: small positions, many concurrent, high win rate

Two modes:
1. Single-side convergence: Buy YES (≥0.90) or NO (YES ≤ 0.10)
   when market outcome is near-certain.
2. Pure arbitrage: Buy BOTH sides when YES_ask + NO_ask < $1
   for guaranteed risk-free profit at resolution.

Uses the DAILY_UPDOWN wallet slot for DB/frontend compatibility.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Set

from app.models import StrategyName, TradeType
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import GAMMA_API

log = logging.getLogger("strategy.convergence")

SCAN_INTERVAL = 10.0
MIN_YES_PRICE = 0.90
MAX_YES_PRICE = 0.985
MAX_NO_TRIGGER = 0.10
ARB_THRESHOLD = 0.997
CLOSE_THRESHOLD = 0.995
MIN_VOLUME = 500
MAX_POSITIONS = 20
POSITION_PCT = 0.04
MAX_CAPITAL_USD = 6.0
MAX_EXPIRY_HOURS = 168.0
MIN_EXPIRY_HOURS = 0.5
REENTRY_COOLDOWN = 300.0

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_open_market_ids: Set[str] = set()
_recently_closed: Dict[str, float] = {}


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
    }


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


def stop():
    global _running
    _running = False


async def _fetch_resolution(market_id: str) -> Optional[str]:
    """Query Gamma API for resolved market. Returns 'YES', 'NO', or None."""
    import json as _json
    session = await md.get_session()
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            prices = data.get("outcomePrices", [])
            if isinstance(prices, str):
                try:
                    prices = _json.loads(prices)
                except Exception:
                    prices = []
            if len(prices) >= 2:
                try:
                    yes_price = float(prices[0])
                    if yes_price >= 0.99:
                        return "YES"
                    if yes_price <= 0.01:
                        return "NO"
                except Exception:
                    pass
            winner = data.get("winner", "") or ""
            if winner.upper() in ("YES", "NO"):
                return winner.upper()
    except Exception as e:
        log.debug(f"Resolution fetch error {market_id}: {e}")
    return None


async def _close_positions(wallet: PaperWallet):
    markets = md.get_markets()
    now = datetime.now(timezone.utc)

    for pos in list(wallet.open_positions):
        if pos.strategy != StrategyName.DAILY_UPDOWN:
            continue

        market = markets.get(pos.market_id)
        close_reason = None
        close_price = 0.5
        is_yes = "BUY_YES" in pos.direction
        is_arb = "ARB" in pos.direction

        if not market:
            resolution = await _fetch_resolution(pos.market_id)
            if resolution is None:
                continue
            if is_arb:
                close_price = 1.0
                close_reason = f"arb_resolved_{resolution}"
            else:
                yes_resolved = (resolution == "YES")
                we_won = (is_yes == yes_resolved)
                close_price = 0.99 if we_won else 0.01
                close_reason = f"resolved_{resolution}_{'WIN' if we_won else 'LOSS'}"
        else:
            end = market.end_date
            if end:
                end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
                secs_left = (end - now).total_seconds()

                if secs_left <= 0:
                    if is_arb:
                        close_price = 1.0
                        close_reason = "arb_expired"
                    else:
                        close_price = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
                        close_price = max(close_price, 0.01)
                        close_reason = "expired"
                elif not is_arb:
                    bid = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
                    if bid >= CLOSE_THRESHOLD:
                        close_price = bid
                        close_reason = f"target_hit bid={bid:.3f}"

        if not close_reason:
            continue

        cost_per_token = pos.cost_basis / pos.size if pos.size else 0
        pnl = round((close_price - cost_per_token) * pos.size, 5)
        tt = TradeType.SELL_YES if is_yes else (TradeType.CLOSE if is_arb else TradeType.SELL_NO)
        await wallet.close_position(pos.id, pnl, close_price, tt, notes=f"Conv close: {close_reason}")
        _open_market_ids.discard(pos.market_id)
        _recently_closed[pos.market_id] = time.time()
        log.info(f"[convergence] CLOSE {close_reason} pnl=${pnl:.4f} | {pos.market_question[:55]}")


async def _update_marks(wallet: PaperWallet):
    markets = md.get_markets()
    for pos in wallet.open_positions:
        if pos.strategy != StrategyName.DAILY_UPDOWN:
            continue
        market = markets.get(pos.market_id)
        if not market:
            continue
        is_yes = "BUY_YES" in pos.direction
        is_arb = "ARB" in pos.direction
        if is_arb:
            combo_bid = market.yes_best_bid + market.no_best_bid
            new_value = round(pos.size * min(combo_bid, 1.0), 4)
        else:
            bid = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
            new_value = round(pos.size * max(bid, 0.01), 4)
        await wallet.update_position_value(pos.id, new_value)


async def scan_once(wallet: PaperWallet):
    global _last_scan, _scan_count

    markets = md.get_markets()
    if not markets:
        return

    _last_scan = datetime.utcnow()
    _scan_count += 1
    wallet.last_scan = _last_scan
    wallet.status = "scanning"
    now = datetime.now(timezone.utc)
    now_ts = time.time()

    await _close_positions(wallet)
    await _update_marks(wallet)

    open_count = sum(1 for p in wallet.open_positions if p.strategy == StrategyName.DAILY_UPDOWN)
    slots = MAX_POSITIONS - open_count
    if slots <= 0:
        wallet.status = "idle"
        return

    candidates: List[Tuple] = []

    for m in markets.values():
        if m.id in _open_market_ids:
            continue
        if now_ts - _recently_closed.get(m.id, 0) < REENTRY_COOLDOWN:
            continue
        if m.volume < MIN_VOLUME:
            continue
        if m.yes_best_ask <= 0 or m.yes_best_bid <= 0:
            continue

        if m.end_date:
            end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
            hrs_left = (end - now).total_seconds() / 3600.0
            if hrs_left < MIN_EXPIRY_HOURS or hrs_left > MAX_EXPIRY_HOURS:
                continue
        else:
            continue

        # Mode 1: Pure arbitrage (buy both sides for < $1)
        if m.no_best_ask > 0:
            combined_ask = m.yes_best_ask + m.no_best_ask
            if combined_ask < ARB_THRESHOLD:
                edge = 1.0 - combined_ask
                candidates.append(("ARB", m, combined_ask, edge, None))
                continue

        # Mode 2: Buy YES convergence (near-certain YES outcome)
        if MIN_YES_PRICE <= m.yes_best_ask <= MAX_YES_PRICE:
            if m.yes_best_bid > 0 and m.yes_best_bid < m.yes_best_ask:
                expected_return = (1.0 - m.yes_best_ask) / m.yes_best_ask
                candidates.append(("BUY_YES", m, m.yes_best_ask, expected_return, True))

        # Mode 3: Buy NO convergence (near-certain NO, i.e. YES very cheap)
        elif m.yes_best_ask <= MAX_NO_TRIGGER and m.no_best_ask > 0:
            no_price = m.no_best_ask
            if MIN_YES_PRICE <= no_price <= MAX_YES_PRICE:
                expected_return = (1.0 - no_price) / no_price
                candidates.append(("BUY_NO", m, no_price, expected_return, False))

    candidates.sort(key=lambda x: x[3], reverse=True)

    log.info(
        f"[convergence] Scan #{_scan_count}: {len(markets)} mkts → "
        f"{len(candidates)} conv/arb candidates (slots={slots})"
    )

    for (mode, m, entry_price, edge, is_yes) in candidates[:slots]:
        if wallet.cash < 1.0:
            break

        cost = min(
            wallet.nav * POSITION_PCT,
            MAX_CAPITAL_USD,
            wallet.cash * 0.9,
        )
        if cost < 0.50:
            continue

        size = round(cost / entry_price, 4)

        if mode == "ARB":
            direction = f"ARB @ {entry_price:.4f}"
            trade_type = TradeType.BUY_BOTH
            notes = f"Conv ARB: combined={entry_price:.4f} edge={edge:.4f} vol=${m.volume:.0f}"
        elif mode == "BUY_YES":
            direction = f"BUY_YES @ {entry_price:.3f}"
            trade_type = TradeType.BUY_YES
            notes = f"Conv YES: ask={entry_price:.4f} exp_ret={edge:.3%} vol=${m.volume:.0f}"
        else:
            direction = f"BUY_NO @ {entry_price:.3f}"
            trade_type = TradeType.BUY_NO
            notes = f"Conv NO: ask={entry_price:.4f} exp_ret={edge:.3%} vol=${m.volume:.0f}"

        pos = await wallet.open_position(
            market_id=m.id,
            market_question=m.question,
            direction=direction,
            cost=round(cost, 4),
            size=size,
            trade_type=trade_type,
            price=entry_price,
            notes=notes,
            resolution_time=m.end_date,
        )

        if pos:
            _open_market_ids.add(m.id)
            log.info(
                f"[convergence] {mode} edge={edge:.3%} ${cost:.2f} | "
                f"{m.question[:65]}"
            )

    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(f"[convergence] Strategy started. YES band={MIN_YES_PRICE}-{MAX_YES_PRICE} max_pos={MAX_POSITIONS}")
    for pos in wallet.open_positions:
        if pos.strategy == StrategyName.DAILY_UPDOWN:
            _open_market_ids.add(pos.market_id)
    await asyncio.sleep(12)
    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[convergence] Scan error: {e}", exc_info=True)
        await asyncio.sleep(SCAN_INTERVAL)
