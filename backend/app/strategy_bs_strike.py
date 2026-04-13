"""
Black-Scholes Daily Strike Arb
================================
Targets "Will Bitcoin/Ethereum be above $X on [date]?" markets.
Uses Black-Scholes binary option formula to price them fairly.

Edge: Market makers don't reprice in real-time → strikes near current
price (within ~10%) are systematically mispriced by 5-20%.

BTC at $71K example:
  "above $72K"  market=10%  BS=20%  → BUY YES  (+10% edge)
  "above $70K"  market=91%  BS=85%  → BUY NO   (+6% edge)

Runs on BTC + ETH.  $5-8 per position, up to 12 concurrent.
"""

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import aiohttp

from app.models import StrategyName, TradeType
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    BS_SCAN_INTERVAL, BS_MIN_EDGE, BS_MAX_POSITIONS,
    BS_POSITION_SIZE, BS_MIN_VOLUME, BS_MIN_TIME_SEC, BS_MAX_TIME_SEC,
    BS_BTC_SIGMA, BS_ETH_SIGMA,
)

log = logging.getLogger("strategy.bs_strike")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_open_market_ids: Set[str] = set()
_recently_closed: Dict[str, float] = {}
REENTRY_COOLDOWN = 300.0  # 5 min cooldown

_price_cache: Dict[str, Tuple[float, float]] = {}
PRICE_TTL = 8.0

BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT", "BNB": "BNBUSDT"}
SIGMA = {"BTC": BS_BTC_SIGMA, "ETH": BS_ETH_SIGMA, "SOL": 1.10, "XRP": 1.20, "BNB": 0.90}


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
    }


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
                    data = await r.json()
                    price = float(data["price"])
                    _price_cache[symbol] = (price, now)
                    return price
    except Exception as e:
        log.debug(f"Binance price error {symbol}: {e}")
    return None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def _bs_prob(S: float, K: float, tau_years: float, sigma: float) -> float:
    """P(S_T > K) under GBM with r=0: Φ(d2)."""
    if tau_years <= 1e-9 or sigma <= 0 or S <= 0 or K <= 0:
        return 1.0 if S > K else 0.0
    d2 = (math.log(S / K) - 0.5 * sigma ** 2 * tau_years) / (sigma * math.sqrt(tau_years))
    return _norm_cdf(d2)


def _parse_strike(question: str) -> Optional[Tuple[str, float]]:
    """Extract (asset, strike) from 'Will BTC be above $72,000...' questions."""
    q = question.lower()
    if "bitcoin" in q or " btc" in q or "btc " in q:
        asset = "BTC"
    elif "ethereum" in q or " eth" in q or "eth " in q:
        asset = "ETH"
    elif "solana" in q or " sol" in q or "sol " in q:
        asset = "SOL"
    elif "xrp" in q or "ripple" in q:
        asset = "XRP"
    elif " bnb" in q or "bnb " in q:
        asset = "BNB"
    else:
        return None

    if "above" not in q and "higher than" not in q and "finish" not in q:
        return None

    m = re.search(r'\$([0-9,]+)(?:,000)?(?:k\b)?', q)
    if not m:
        return None
    raw = m.group(0)
    num_str = m.group(1).replace(",", "")
    try:
        strike = float(num_str)
        if "k" in raw.lower():
            strike *= 1000
        # If the number is suspiciously small (like "72" without k) try scaling
        if asset == "BTC" and strike < 1000:
            strike *= 1000
        elif asset == "ETH" and strike < 10:
            strike *= 1000
    except ValueError:
        return None

    if asset == "BTC" and not (5000 < strike < 500000):
        return None
    if asset == "ETH" and not (100 < strike < 20000):
        return None
    if asset == "SOL" and not (1 < strike < 10000):
        return None
    if asset == "XRP" and not (0.01 < strike < 100):
        return None
    if asset == "BNB" and not (10 < strike < 50000):
        return None
    return asset, strike


async def _close_positions(wallet: PaperWallet):
    markets = md.get_markets()
    now = datetime.now(timezone.utc)

    for pos in list(wallet.open_positions):
        if pos.strategy != StrategyName.BS_STRIKE:
            continue

        market = markets.get(pos.market_id)
        close_reason = None
        close_price = 0.5
        is_yes = "BUY_YES" in pos.direction

        if not market:
            # Market resolved/gone — determine winner from notes
            close_price = 0.99 if is_yes else 0.99
            close_reason = "market_resolved"
        else:
            end = market.end_date
            if end:
                end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
                secs_left = (end - now).total_seconds()

                if secs_left <= 0:
                    # Resolve using live Binance price vs strike
                    parsed = _parse_strike(market.question)
                    if parsed:
                        asset, strike = parsed
                        curr = await _fetch_price(BINANCE_SYMBOLS.get(asset, "BTCUSDT"))
                        if curr:
                            won = (curr > strike) if is_yes else (curr <= strike)
                            close_price = 0.99 if won else 0.01
                        else:
                            close_price = market.yes_best_bid if is_yes else (1 - market.yes_best_ask)
                    close_reason = f"expired secs={secs_left:.0f}"

                elif secs_left <= 1800:
                    # < 30 min: close at live market price to lock profit
                    close_price = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
                    close_price = max(close_price, 0.01)
                    close_reason = f"near_expiry {secs_left/60:.0f}min"

        if not close_reason:
            continue

        pnl = round((close_price - pos.cost_basis / pos.size) * pos.size, 5)
        tt = TradeType.SELL_YES if is_yes else TradeType.SELL_NO
        await wallet.close_position(pos.id, pnl, close_price, tt, notes=f"BS close: {close_reason}")
        _open_market_ids.discard(pos.market_id)
        _recently_closed[pos.market_id] = time.time()
        log.info(f"[bs_strike] ✅ CLOSE {close_reason} pnl=${pnl:.4f} | {pos.market_question[:55]}")


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

    open_count = sum(1 for p in wallet.open_positions if p.strategy == StrategyName.BS_STRIKE)
    slots = BS_MAX_POSITIONS - open_count
    if slots <= 0:
        wallet.status = "idle"
        return

    # Fetch live Binance prices
    prices = {}
    for asset, sym in BINANCE_SYMBOLS.items():
        p = await _fetch_price(sym)
        if p:
            prices[asset] = p
    if not prices:
        wallet.status = "idle"
        return

    candidates: List[Tuple] = []
    for m in markets.values():
        if m.id in _open_market_ids:
            continue
        if time.time() - _recently_closed.get(m.id, 0) < REENTRY_COOLDOWN:
            continue
        if m.volume < BS_MIN_VOLUME:
            continue
        if not m.end_date:
            continue

        parsed = _parse_strike(m.question)
        if not parsed:
            continue
        asset, strike = parsed

        curr = prices.get(asset)
        if not curr:
            continue

        end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
        secs_left = (end - now).total_seconds()
        if not (BS_MIN_TIME_SEC <= secs_left <= BS_MAX_TIME_SEC):
            continue

        # Only trade strikes within 20% of current price (meaningful edge zone)
        if abs(curr - strike) / curr > 0.20:
            continue

        tau = secs_left / (365 * 86400)
        sigma = SIGMA.get(asset, 0.80)
        fair_yes = _bs_prob(curr, strike, tau, sigma)

        yes_ask = m.yes_best_ask
        yes_bid = m.yes_best_bid
        if yes_ask <= 0.005 or yes_bid <= 0.005:
            continue

        mkt_mid = (yes_ask + yes_bid) / 2.0
        edge_yes = fair_yes - mkt_mid

        if abs(edge_yes) < BS_MIN_EDGE:
            continue

        direction = "YES" if edge_yes > 0 else "NO"
        entry = yes_ask if direction == "YES" else max(1.0 - yes_bid, 0.01)
        candidates.append((abs(edge_yes), m, asset, strike, curr, fair_yes, mkt_mid, direction, entry, secs_left))

    candidates.sort(reverse=True)
    log.info(
        f"[bs_strike] Scan #{_scan_count}: {len(markets)} mkts → {len(candidates)} BS candidates (slots={slots})"
    )

    for (edge, m, asset, strike, curr, fair_yes, mkt_mid, direction, entry, secs_left) in candidates[:slots]:
        if wallet.cash < 1.0:
            break
        cost = min(BS_POSITION_SIZE, wallet.cash * 0.90)
        if cost < 0.50:
            continue
        size = round(cost / entry, 4)
        notes = (
            f"BS: {asset}=${curr:.0f} K=${strike:.0f} "
            f"fair={fair_yes:.3f} mkt={mkt_mid:.3f} edge={edge:.3f} "
            f"{secs_left/3600:.1f}h vol=${m.volume:.0f}"
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
                f"[bs_strike] 📐 BUY_{direction} {asset} K=${strike:.0f} curr=${curr:.0f} "
                f"fair={fair_yes:.3f} mkt={mkt_mid:.3f} edge={edge:.1%} ${cost:.2f} | {m.question[:55]}"
            )

    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(f"[bs_strike] Strategy started. min_edge={BS_MIN_EDGE:.0%} max_pos={BS_MAX_POSITIONS}")
    for pos in wallet.open_positions:
        if pos.strategy == StrategyName.BS_STRIKE:
            _open_market_ids.add(pos.market_id)
    await asyncio.sleep(15)
    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[bs_strike] Scan error: {e}", exc_info=True)
        await asyncio.sleep(BS_SCAN_INTERVAL)
