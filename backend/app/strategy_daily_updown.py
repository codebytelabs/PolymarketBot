"""
Daily Up/Down Direction Strategy
===================================
Targets "Will Bitcoin close UP or DOWN today?" binary markets.

Uses today's Binance day-open price + current price + Black-Scholes
GBM drift to compute P(close > open).  Bets when market disagrees by
more than UD_MIN_EDGE.

With BTC already up 0.5% and 3h left in the day, P(day close > open)
is ~65-70% — if market only shows YES at 52¢ that's a clear edge.

Covers BTC, ETH, SOL, XRP.  $5 per position, up to 8 concurrent.
"""

import asyncio
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple

import aiohttp

from app.models import StrategyName, TradeType
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    UD_SCAN_INTERVAL, UD_MIN_EDGE, UD_MAX_POSITIONS,
    UD_POSITION_SIZE, UD_MIN_VOLUME, UD_BTC_SIGMA, UD_ETH_SIGMA,
    GAMMA_API,
)

log = logging.getLogger("strategy.daily_updown")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_open_market_ids: Set[str] = set()
_recently_closed: Dict[str, float] = {}
REENTRY_COOLDOWN = 120.0  # 2 min cooldown — 5-min markets are rapid

_price_cache: Dict[str, Tuple[float, float]] = {}
_open_price_cache: Dict[str, Tuple[float, float]] = {}
PRICE_TTL = 8.0
OPEN_PRICE_TTL = 300.0  # day-open changes only at midnight

BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT", "BNB": "BNBUSDT"}
SIGMA = {"BTC": UD_BTC_SIGMA, "ETH": UD_ETH_SIGMA, "SOL": 1.10, "XRP": 1.20, "BNB": 0.90}

ASSET_KEYWORDS = {
    "BTC": ["bitcoin", " btc", "btc "],
    "ETH": ["ethereum", " eth", "eth "],
    "SOL": ["solana", " sol", "sol "],
    "XRP": [" xrp", "xrp ", "ripple"],
    "BNB": [" bnb", "bnb "],
}
UPDOWN_KEYWORDS = ["up or down", "higher or lower", "close up", "up on", "up today", "updown"]


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
    }


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
        log.debug(f"[daily_updown] Resolution fetch error {market_id}: {e}")
    return None


def stop():
    global _running
    _running = False


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


async def _fetch_price(symbol: str) -> Optional[float]:
    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and (now - cached[1]) < PRICE_TTL:
        return cached[0]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    p = float(d["price"])
                    _price_cache[symbol] = (p, now)
                    return p
    except Exception as e:
        log.debug(f"Price error {symbol}: {e}")
    return None


async def _fetch_day_open(symbol: str) -> Optional[float]:
    """Get today's UTC day-open price from Binance daily kline."""
    now = time.time()
    cached = _open_price_cache.get(symbol)
    if cached and (now - cached[1]) < OPEN_PRICE_TTL:
        return cached[0]
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=1"
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    data = await r.json()
                    if data:
                        open_price = float(data[0][1])  # kline[1] = open
                        _open_price_cache[symbol] = (open_price, now)
                        return open_price
    except Exception as e:
        log.debug(f"Day-open error {symbol}: {e}")
    return None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def _prob_close_above_open(curr: float, day_open: float, secs_remaining: float, sigma: float) -> float:
    """
    P(S_T > S_0) given current price S_curr, day open S_0, with T seconds remaining.
    Uses GBM: conditioned on current path, remaining uncertainty is sigma * sqrt(tau_remaining).
    """
    if secs_remaining <= 0:
        return 1.0 if curr > day_open else 0.0
    tau = secs_remaining / (365 * 86400)
    log_ret = math.log(curr / day_open)
    d = (log_ret - 0.5 * sigma ** 2 * tau) / (sigma * math.sqrt(tau))
    return _norm_cdf(d)


def _detect_asset(question: str) -> Optional[str]:
    q = question.lower()
    for asset, kws in ASSET_KEYWORDS.items():
        if any(kw in q for kw in kws):
            return asset
    return None


def _is_updown_market(question: str, event_slug: str) -> bool:
    text = (question + " " + (event_slug or "")).lower()
    if any(kw in text for kw in UPDOWN_KEYWORDS):
        return True
    # Also match slug patterns like 'btc-updown-5m', 'eth-updown-15m'
    if "-updown-" in text or "-up-or-down" in text:
        return True
    return False


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

        if not market:
            # Query actual YES/NO resolution instead of blindly assuming a win
            resolution = await _fetch_resolution(pos.market_id)
            if resolution is None:
                log.debug(f"[daily_updown] Resolution unknown for {pos.market_id[:12]}, retrying")
                continue
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
                    # Resolve at current market bid
                    close_price = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
                    close_price = max(close_price, 0.01)
                    close_reason = "expired"
                elif secs_left <= 30:
                    close_price = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
                    close_price = max(close_price, 0.01)
                    close_reason = f"near_expiry {secs_left:.0f}s"

        if not close_reason:
            continue

        pnl = round((close_price - pos.cost_basis / pos.size) * pos.size, 5)
        tt = TradeType.SELL_YES if is_yes else TradeType.SELL_NO
        await wallet.close_position(pos.id, pnl, close_price, tt, notes=f"UD close: {close_reason}")
        _open_market_ids.discard(pos.market_id)
        _recently_closed[pos.market_id] = time.time()
        log.info(f"[daily_updown] ✅ CLOSE {close_reason} pnl=${pnl:.4f} | {pos.market_question[:55]}")


async def _update_marks(wallet: PaperWallet):
    markets = md.get_markets()
    for pos in wallet.open_positions:
        if pos.strategy != StrategyName.DAILY_UPDOWN:
            continue
        market = markets.get(pos.market_id)
        if not market:
            continue
        is_yes = "BUY_YES" in pos.direction
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

    await _close_positions(wallet)
    await _update_marks(wallet)

    open_count = sum(1 for p in wallet.open_positions if p.strategy == StrategyName.DAILY_UPDOWN)
    slots = UD_MAX_POSITIONS - open_count
    if slots <= 0:
        wallet.status = "idle"
        return

    # Fetch prices and day-opens for all assets
    prices: Dict[str, float] = {}
    day_opens: Dict[str, float] = {}
    for asset, sym in BINANCE_SYMBOLS.items():
        p = await _fetch_price(sym)
        o = await _fetch_day_open(sym)
        if p:
            prices[asset] = p
        if o:
            day_opens[asset] = o

    candidates: List[Tuple] = []
    for m in markets.values():
        if m.id in _open_market_ids:
            continue
        if time.time() - _recently_closed.get(m.id, 0) < REENTRY_COOLDOWN:
            continue
        if m.volume < UD_MIN_VOLUME:
            continue
        if not m.end_date:
            continue

        if not _is_updown_market(m.question, m.event_slug or ""):
            continue

        asset = _detect_asset(m.question)
        if not asset:
            continue

        curr = prices.get(asset)
        day_open = day_opens.get(asset)
        if not curr or not day_open:
            continue

        end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
        secs_left = (end - now).total_seconds()

        # Enter with 30s to 24h remaining — 5-min markets need quick entry
        if not (30 <= secs_left <= 86400):
            continue

        sigma = SIGMA.get(asset, 0.80)
        fair_yes = _prob_close_above_open(curr, day_open, secs_left, sigma)

        yes_ask = m.yes_best_ask
        yes_bid = m.yes_best_bid
        if yes_ask <= 0.01 or yes_bid <= 0.01:
            continue

        mkt_mid = (yes_ask + yes_bid) / 2.0
        edge_yes = fair_yes - mkt_mid

        if abs(edge_yes) < UD_MIN_EDGE:
            continue

        direction = "YES" if edge_yes > 0 else "NO"
        entry = yes_ask if direction == "YES" else max(1.0 - yes_bid, 0.01)
        pct_move = (curr - day_open) / day_open * 100
        candidates.append((abs(edge_yes), m, asset, curr, day_open, pct_move, fair_yes, mkt_mid, direction, entry, secs_left))

    candidates.sort(reverse=True)
    log.info(
        f"[daily_updown] Scan #{_scan_count}: {len(markets)} mkts → {len(candidates)} UD candidates (slots={slots})"
    )

    for (edge, m, asset, curr, day_open, pct_move, fair_yes, mkt_mid, direction, entry, secs_left) in candidates[:slots]:
        if wallet.cash < 1.0:
            break
        cost = min(UD_POSITION_SIZE, wallet.cash * 0.90)
        if cost < 0.50:
            continue
        size = round(cost / entry, 4)
        time_label = f"{secs_left/60:.0f}min" if secs_left < 3600 else f"{secs_left/3600:.1f}h"
        notes = (
            f"UD: {asset} curr={curr:.2f} open={day_open:.2f} move={pct_move:+.2f}% "
            f"fair={fair_yes:.3f} mkt={mkt_mid:.3f} edge={edge:.3f} {time_label}"
        )
        pos = await wallet.open_position(
            market_id=m.id,
            market_question=m.question,
            direction=f"BUY_{direction} @ {entry:.3f}",
            cost=round(cost, 4),
            size=size,
            trade_type=TradeType.BUY_YES if direction == "YES" else TradeType.BUY_NO,
            price=entry,
            notes=notes,
            resolution_time=m.end_date,
        )
        if pos:
            _open_market_ids.add(m.id)
            log.info(
                f"[daily_updown] 📈 BUY_{direction} {asset} curr={curr:.2f} open={day_open:.2f} "
                f"move={pct_move:+.2f}% fair={fair_yes:.3f} mkt={mkt_mid:.3f} edge={edge:.1%} "
                f"${cost:.2f} | {m.question[:55]}"
            )

    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(f"[daily_updown] Strategy started. min_edge={UD_MIN_EDGE:.0%} max_pos={UD_MAX_POSITIONS}")
    for pos in wallet.open_positions:
        if pos.strategy == StrategyName.DAILY_UPDOWN:
            _open_market_ids.add(pos.market_id)
    await asyncio.sleep(18)
    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[daily_updown] Scan error: {e}", exc_info=True)
        await asyncio.sleep(UD_SCAN_INTERVAL)
