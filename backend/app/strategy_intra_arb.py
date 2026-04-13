import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional

from app.models import StrategyName, TradeType
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    INTRA_ARB_SCAN_INTERVAL, INTRA_ARB_MIN_EDGE,
    INTRA_ARB_FEE_ESTIMATE, INTRA_ARB_MAX_POSITION_PCT,
    INTRA_ARB_MAX_TRADE_USD
)

log = logging.getLogger("strategy.intra_arb")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_opportunities_this_session = 0
_recently_traded: Dict[str, float] = {}
TRADE_COOLDOWN_SEC = 45.0


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
        "opportunities_this_session": _opportunities_this_session,
        "scan_interval_sec": INTRA_ARB_SCAN_INTERVAL,
        "min_edge_threshold": INTRA_ARB_MIN_EDGE,
    }


def _detect_arb(m) -> Optional[tuple]:
    """
    Detects ONLY genuine CLOB-level arbitrage using live order book prices.

    Buy-side:  yes_ask + no_ask < 1.0  →  buy both for < $1, collect $1 at resolution.
    Sell-side: yes_bid + no_bid > 1.0  →  collective bids over-commit beyond $1 payout.

    NEVER uses Gamma / aggregate prices (outcomePrices) — those are stale and create
    phantom edges that cannot be realised in live trading.
    """
    yes_ask = m.yes_best_ask
    no_ask  = m.no_best_ask
    yes_bid = m.yes_best_bid
    no_bid  = m.no_best_bid

    # Require fully populated live CLOB data; skip if any side is missing
    if not (0 < yes_ask < 1 and 0 < no_ask < 1 and yes_bid > 0 and no_bid > 0):
        return None
    # Basic sanity: bids must be below asks
    if yes_bid >= yes_ask or no_bid >= no_ask:
        return None

    # Buy-side: combined ask < $1  →  guaranteed risk-free profit at resolution
    combined_ask = yes_ask + no_ask
    buy_edge = 1.0 - combined_ask - INTRA_ARB_FEE_ESTIMATE * 2
    if buy_edge >= INTRA_ARB_MIN_EDGE:
        return ("BUY_BOTH", combined_ask, buy_edge)

    # Sell-side: combined bid > $1  →  over-committed market (rare but real)
    combined_bid = yes_bid + no_bid
    sell_edge = combined_bid - 1.0 - INTRA_ARB_FEE_ESTIMATE * 2
    if sell_edge >= INTRA_ARB_MIN_EDGE:
        return ("SELL_BOTH", combined_bid, sell_edge)

    return None


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
        result = _detect_arb(m)
        if result:
            candidates.append((m, result[0], result[1], result[2]))

    candidates.sort(key=lambda x: x[3], reverse=True)
    log.info(f"[intra_arb] Scan #{_scan_count}: {len(markets)} markets → {len(candidates)} arb opportunities")

    for market, arb_type, entry_price, net_edge in candidates[:5]:
        if wallet.cash < 2.0:
            log.info(f"[intra_arb] Low cash ${wallet.cash:.2f}, pausing trades")
            break

        max_spend = min(wallet.nav * INTRA_ARB_MAX_POSITION_PCT, INTRA_ARB_MAX_TRADE_USD)
        available = min(wallet.cash * 0.9, max_spend)
        size = round(available / max(entry_price, 0.01), 2)
        if size < 0.5:
            continue

        cost = round(size * entry_price, 4)
        net_profit = round(size * net_edge, 4)
        if net_profit <= 0:
            continue

        notes = (
            f"type={arb_type} entry={entry_price:.4f} edge={net_edge:.4f} "
            f"gamma_price={market.yes_price:.4f} clob_mid={market.mid:.4f} "
            f"yes_ask={market.yes_best_ask:.4f} no_ask={market.no_best_ask:.4f}"
        )

        pos = await wallet.open_position(
            market_id=market.id,
            market_question=market.question,
            direction=arb_type,
            cost=cost,
            size=size,
            trade_type=TradeType.BUY_BOTH,
            price=entry_price,
            notes=notes,
            resolution_time=market.end_date,
        )
        if pos:
            _opportunities_this_session += 1
            close_price = round(entry_price + net_edge, 4)
            await wallet.close_position(
                pos_id=pos.id,
                pnl=net_profit,
                close_price=close_price,
                trade_type=TradeType.CLOSE,
                notes=f"Arb locked profit=${net_profit:.4f} type={arb_type}"
            )
            _recently_traded[market.id] = now_ts
            log.info(
                f"[intra_arb] ✅ {arb_type} ${net_profit:.4f} | "
                f"{market.question[:70]} | edge={net_edge:.4f}"
            )

    await _update_open_position_marks(wallet, markets)
    wallet.status = "idle"


async def _update_open_position_marks(wallet: PaperWallet, markets):
    for pos in wallet.open_positions:
        m = markets.get(pos.market_id)
        if not m:
            continue
        combo_bid = m.yes_best_bid + m.no_best_bid
        if combo_bid > 0:
            mark_value = pos.size * min(combo_bid, 1.0)
            await wallet.update_position_value(pos.id, mark_value)


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(f"[intra_arb] Strategy started. Min edge={INTRA_ARB_MIN_EDGE}, interval={INTRA_ARB_SCAN_INTERVAL}s")

    await asyncio.sleep(5)

    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[intra_arb] Scan error: {e}", exc_info=True)
        await asyncio.sleep(INTRA_ARB_SCAN_INTERVAL)


def stop():
    global _running
    _running = False
