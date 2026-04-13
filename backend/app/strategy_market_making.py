import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from app.models import StrategyName, TradeType, PositionStatus
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    MM_SCAN_INTERVAL, MM_MIN_SPREAD, MM_QUOTE_HALF_SPREAD,
    MM_MAX_POSITION_PCT, MM_LP_REWARD_RATE_PER_HOUR, MM_MAX_QUOTE_CAPITAL_USD
)

log = logging.getLogger("strategy.market_making")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_opportunities_this_session = 0
_lp_capital_deployed = 0.0
_last_lp_reward_time: Optional[datetime] = None
_active_quotes: Dict[str, Dict] = {}


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
        "opportunities_this_session": _opportunities_this_session,
        "scan_interval_sec": MM_SCAN_INTERVAL,
        "min_spread_threshold": MM_MIN_SPREAD,
        "active_quotes": len(_active_quotes),
        "lp_capital_deployed": round(_lp_capital_deployed, 2),
    }


async def _accrue_lp_rewards(wallet: PaperWallet):
    global _last_lp_reward_time, _lp_capital_deployed
    if _last_lp_reward_time is None:
        _last_lp_reward_time = datetime.utcnow()
        return
    now = datetime.utcnow()
    elapsed_hours = (now - _last_lp_reward_time).total_seconds() / 3600.0
    if elapsed_hours < (MM_SCAN_INTERVAL / 3600.0):
        return
    deployed = min(_lp_capital_deployed, wallet.nav * 0.5)
    if deployed < 1.0:
        return
    reward = deployed * MM_LP_REWARD_RATE_PER_HOUR * elapsed_hours
    if reward > 0.00001:
        await wallet.add_lp_reward(
            amount=round(reward, 6),
            market_id="lp_pool",
            notes=f"LP reward: ${deployed:.2f} deployed × {elapsed_hours:.4f}h × {MM_LP_REWARD_RATE_PER_HOUR:.4f}/h"
        )
        _last_lp_reward_time = now
        log.debug(f"[market_making] LP reward accrued: ${reward:.6f}")


async def _check_quote_fills(wallet: PaperWallet, markets):
    global _active_quotes
    filled = []
    for market_id, quote in list(_active_quotes.items()):
        m = markets.get(market_id)
        if not m:
            filled.append(market_id)
            continue

        current_mid = m.mid if m.mid > 0 else 0.5
        quote_mid = quote["mid"]
        price_move = abs(current_mid - quote_mid)

        # Price must cross the quoted level, not just approach it (reduces false fills)
        bid_filled = current_mid < quote["bid"] - 0.005
        ask_filled = current_mid > quote["ask"] + 0.005
        age_seconds = (datetime.utcnow() - quote["placed_at"]).total_seconds()

        if bid_filled and not quote.get("bid_filled"):
            # ~0.15% of capital per fill — realistic for prediction market MM
            spread_profit = round(quote["half_spread"] * quote["capital"] * 0.08, 5)
            pos = await wallet.open_position(
                market_id=market_id,
                market_question=m.question,
                direction=f"MM_BID_FILL mid={current_mid:.3f}",
                cost=round(quote["bid"] * quote["size"], 4),
                size=quote["size"],
                trade_type=TradeType.MM_BID,
                price=quote["bid"],
                notes=f"MM bid filled at {quote['bid']:.4f}, spread={quote['half_spread']*2:.4f}"
            )
            if pos:
                await wallet.close_position(
                    pos_id=pos.id,
                    pnl=spread_profit,
                    close_price=current_mid,
                    trade_type=TradeType.CLOSE,
                    notes=f"MM spread captured ${spread_profit:.5f}"
                )
                log.info(f"[market_making] ✅ MM BID filled ${spread_profit:.5f} | {m.question[:60]}")
                quote["bid_filled"] = True
                _opportunities_this_session += 1

        if ask_filled and not quote.get("ask_filled"):
            spread_profit = round(quote["half_spread"] * quote["capital"] * 0.08, 5)
            pos = await wallet.open_position(
                market_id=market_id,
                market_question=m.question,
                direction=f"MM_ASK_FILL mid={current_mid:.3f}",
                cost=round((1 - quote["ask"]) * quote["size"], 4),
                size=quote["size"],
                trade_type=TradeType.MM_ASK,
                price=quote["ask"],
                notes=f"MM ask filled at {quote['ask']:.4f}, spread={quote['half_spread']*2:.4f}"
            )
            if pos:
                await wallet.close_position(
                    pos_id=pos.id,
                    pnl=spread_profit,
                    close_price=current_mid,
                    trade_type=TradeType.CLOSE,
                    notes=f"MM spread captured ${spread_profit:.5f}"
                )
                log.info(f"[market_making] ✅ MM ASK filled ${spread_profit:.5f} | {m.question[:60]}")
                quote["ask_filled"] = True
                _opportunities_this_session += 1

        if age_seconds > 120 or (quote.get("bid_filled") and quote.get("ask_filled")):
            filled.append(market_id)

    for mid in filled:
        _active_quotes.pop(mid, None)


async def scan_once(wallet: PaperWallet):
    global _last_scan, _scan_count, _lp_capital_deployed
    markets = md.get_markets()
    if not markets:
        return

    _last_scan = datetime.utcnow()
    _scan_count += 1
    wallet.last_scan = _last_scan
    wallet.status = "scanning"

    await _check_quote_fills(wallet, markets)
    await _accrue_lp_rewards(wallet)

    candidates = []
    for m in markets.values():
        if m.id in _active_quotes:
            continue
        if m.spread < MM_MIN_SPREAD:
            continue
        if m.mid <= 0.02 or m.mid >= 0.98:
            continue
        if m.volume < 2000:
            continue
        candidates.append((m, m.spread))

    candidates.sort(key=lambda x: x[1], reverse=True)
    log.info(f"[market_making] Scan #{_scan_count}: {len(markets)} markets → {len(candidates)} MM candidates")

    max_new_quotes = min(3, 8 - len(_active_quotes))
    lp_total = 0.0

    for market, spread in candidates[:max_new_quotes]:
        if wallet.cash < 2.0:
            break

        max_spend = wallet.nav * MM_MAX_POSITION_PCT
        # Hard cap per quote: prevents profit/fill from scaling with NAV (no runaway compounding)
        quote_capital = min(wallet.cash * 0.15, max_spend, MM_MAX_QUOTE_CAPITAL_USD)
        if quote_capital < 1.0:
            continue

        half_spread = max(MM_QUOTE_HALF_SPREAD, spread * 0.4)
        bid = round(market.mid - half_spread, 4)
        ask = round(market.mid + half_spread, 4)
        bid = max(0.01, min(bid, 0.97))
        ask = max(0.03, min(ask, 0.99))
        size = round(quote_capital / market.mid, 2)

        _active_quotes[market.id] = {
            "mid": market.mid,
            "bid": bid,
            "ask": ask,
            "half_spread": half_spread,
            "size": size,
            "capital": quote_capital,
            "placed_at": datetime.utcnow(),
            "bid_filled": False,
            "ask_filled": False,
            "market_question": market.question,
        }
        lp_total += quote_capital
        log.info(
            f"[market_making] 📋 QUOTE placed | mid={market.mid:.3f} "
            f"bid={bid:.3f} ask={ask:.3f} spread={spread:.4f} | {market.question[:60]}"
        )

    _lp_capital_deployed = lp_total + sum(
        q.get("capital", 0) for q in _active_quotes.values()
    )
    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running, _last_lp_reward_time
    _wallet = wallet
    _running = True
    _last_lp_reward_time = datetime.utcnow()
    log.info(f"[market_making] Strategy started. Min spread={MM_MIN_SPREAD}, interval={MM_SCAN_INTERVAL}s")

    await asyncio.sleep(12)

    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[market_making] Scan error: {e}", exc_info=True)
        await asyncio.sleep(MM_SCAN_INTERVAL)


def stop():
    global _running
    _running = False
