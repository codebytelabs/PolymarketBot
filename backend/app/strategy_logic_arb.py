import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from app.models import StrategyName, TradeType
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    LOGIC_ARB_SCAN_INTERVAL, LOGIC_ARB_MIN_EDGE, LOGIC_ARB_MAX_TRADE_USD,
    LOGIC_ARB_TIER1_PCT, LOGIC_ARB_TIER2_PCT, LOGIC_ARB_TIER3_PCT,
    LOGIC_ARB_TIER2_NAV, LOGIC_ARB_TIER3_NAV, LOGIC_ARB_MAX_GROUP_SIZE,
)

log = logging.getLogger("strategy.logic_arb")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_opportunities_this_session = 0
_recently_traded_overpriced: Dict[str, float] = {}   # 1-hour cooldown
_recently_traded_threshold: Dict[str, float] = {}   # 24-hour cooldown
OVERPRICED_COOLDOWN_SEC = 86400.0  # once per day — same as threshold; restarts must not replay same groups
THRESHOLD_COOLDOWN_SEC = 86400.0   # threshold violation = trade once per day (consumed liquidity)


def _position_pct(nav: float) -> float:
    """Tiered position sizing: aggressive at small NAV, tapers as wallet grows."""
    if nav > LOGIC_ARB_TIER3_NAV:
        return LOGIC_ARB_TIER3_PCT
    if nav > LOGIC_ARB_TIER2_NAV:
        return LOGIC_ARB_TIER2_PCT
    return LOGIC_ARB_TIER1_PCT


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
        "opportunities_this_session": _opportunities_this_session,
        "scan_interval_sec": LOGIC_ARB_SCAN_INTERVAL,
        "min_edge_threshold": LOGIC_ARB_MIN_EDGE,
    }


def _group_markets_by_event(markets) -> Dict[str, List]:
    groups: Dict[str, List] = defaultdict(list)
    for m in markets.values():
        key = m.event_slug or m.category or "misc"
        if key:
            groups[key].append(m)
    return groups


# Market question keywords that indicate NON-EXCLUSIVE outcomes.
# These markets can ALL be true simultaneously, so sum(YES)>1 is expected — NOT an arb.
_NON_EXCLUSIVE_KEYWORDS = [
    "top 3", "top 5", "top 10", "top 20", "top 50", "top 100",
    "qualify", "qualification", "advance to", "make the",
    "finish in the top", "end the year in", "place in",
    "podium", "medal", "knockout", "nominated",
]


def _detect_overpriced_outcomes(group: List) -> Optional[Tuple]:
    """
    Detects groups where sum(YES asks) > 1.0 using LIVE CLOB prices only.
    Only valid for EXCLUSIVE outcome markets (one winner, one elected).
    Never falls back to Gamma outcomePrices (stale, unreliable).
    Requires both yes_best_ask and no_best_ask to be populated for each market.
    """
    if len(group) < 2:
        return None

    # Skip groups where any market has non-exclusive question phrasing
    for m in group:
        q = m.question.lower()
        if any(kw in q for kw in _NON_EXCLUSIVE_KEYWORDS):
            return None

    yes_prices = []
    for m in group:
        # Require both sides of the CLOB to compute a reliable mid
        if m.yes_best_ask <= 0 or m.yes_best_bid <= 0 or m.no_best_ask <= 0:
            continue
        # Use mid price so the bid-ask spread doesn't create phantom arbs
        yes_mid = (m.yes_best_bid + m.yes_best_ask) / 2.0
        if not (0.04 < yes_mid < 0.96):
            continue
        yes_prices.append((m, yes_mid))

    if len(yes_prices) < 2:
        return None

    total_yes = sum(p for _, p in yes_prices)
    # Only genuine overpricing above fair value counts; bid-ask spread is excluded
    if total_yes <= 1.0 + LOGIC_ARB_MIN_EDGE:
        return None

    overpriced = sorted(yes_prices, key=lambda x: x[1], reverse=True)
    return overpriced, total_yes


def _detect_threshold_violations(group: List) -> Optional[Tuple]:
    threshold_keywords = ["above", "over", "exceed", "more than", "greater than",
                          "below", "under", "less than"]
    threshold_markets = [
        m for m in group
        if any(kw in m.question.lower() for kw in threshold_keywords)
    ]
    if len(threshold_markets) < 2:
        return None

    def extract_threshold(q: str) -> Optional[float]:
        import re
        patterns = [
            r'\$?([\d,]+(?:\.\d+)?)[kK]?\s*(?:billion|trillion|million)?',
        ]
        nums = []
        for pat in patterns:
            matches = re.findall(pat, q.replace(",", ""))
            for m in matches:
                try:
                    v = float(m)
                    if 1 < v < 10_000_000:
                        nums.append(v)
                except Exception:
                    pass
        return nums[0] if nums else None

    parsed = []
    for m in threshold_markets:
        t = extract_threshold(m.question)
        # ONLY use live CLOB ask — skip markets with no book data or extreme prices
        # Prices near 0 or 1 indicate resolved/near-certain markets: NO token is worthless
        if t and m.yes_best_ask > 0 and m.no_best_ask > 0 and 0.04 < m.yes_best_ask < 0.96:
            parsed.append((m, t, m.yes_best_ask))

    if len(parsed) < 2:
        return None

    parsed.sort(key=lambda x: x[1])
    violations = []
    for i in range(len(parsed) - 1):
        m_lower, t_lower, p_lower = parsed[i]
        m_higher, t_higher, p_higher = parsed[i + 1]
        is_above = "above" in m_lower.question.lower() or "over" in m_lower.question.lower()
        if is_above and p_higher > p_lower + LOGIC_ARB_MIN_EDGE:
            violations.append((m_lower, m_higher, p_lower, p_higher, p_higher - p_lower))

    if violations:
        violations.sort(key=lambda x: x[4], reverse=True)
        return violations[0]
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

    groups = _group_markets_by_event(markets)
    log.info(f"[logic_arb] Scan #{_scan_count}: {len(markets)} markets in {len(groups)} event groups")

    now_ts = time.time()
    arbs_found = 0
    for event_key, group in groups.items():
        if wallet.cash < 3.0:
            break

        # Only check exclusive-outcome groups (elections, binary pairs).
        # Non-exclusive groups (top-N, qualifications, awards) naturally have sum(YES)>1 — NOT an arb.
        if len(group) > LOGIC_ARB_MAX_GROUP_SIZE:
            result = None
        else:
            result = _detect_overpriced_outcomes(group)
        if result:
            # 1-hour cooldown: short-term sum>1 inefficiency; re-enter once per hour only
            if now_ts - _recently_traded_overpriced.get(event_key, 0) < OVERPRICED_COOLDOWN_SEC:
                pass  # fall through to threshold check below
            else:
                overpriced_list, total_yes = result
                arbs_found += 1
                _opportunities_this_session += 1

                target_market, target_price = overpriced_list[0]
                # Entry is the live NO ask (actual cost to buy NO on the overpriced outcome)
                no_price = target_market.no_best_ask if target_market.no_best_ask > 0 else (1 - target_price)
                edge = total_yes - 1.0 - 0.01
                if edge >= LOGIC_ARB_MIN_EDGE:
                    max_spend = min(wallet.nav * _position_pct(wallet.nav), LOGIC_ARB_MAX_TRADE_USD)
                    cost = min(wallet.cash * 0.85, max_spend)
                    size = round(cost / no_price, 2) if no_price > 0 else 0
                    if size >= 0.5:
                        actual_cost = round(size * no_price, 4)
                        # PnL reflects probabilistic (not risk-free) edge: 50% discount for uncertainty
                        pnl = round(actual_cost * (edge / total_yes) * 0.5, 4)
                        notes = (
                            f"Logic arb: group={event_key[:40]} total_yes={total_yes:.3f} "
                            f"edge={edge:.3f} buying NO on overpriced={target_price:.3f} (CLOB only)"
                        )
                        pos = await wallet.open_position(
                            market_id=target_market.id,
                            market_question=target_market.question,
                            direction=f"BUY_NO (logic overpriced, sum={total_yes:.3f})",
                            cost=actual_cost,
                            size=size,
                            trade_type=TradeType.HEDGE,
                            price=no_price,
                            notes=notes,
                            resolution_time=target_market.end_date,
                        )
                        if pos:
                            await wallet.close_position(
                                pos_id=pos.id,
                                pnl=pnl,
                                close_price=no_price,
                                trade_type=TradeType.CLOSE,
                                notes=f"Logic arb closed, pnl=${pnl:.3f}"
                            )
                            _recently_traded_overpriced[event_key] = now_ts
                            log.info(
                                f"[logic_arb] ✅ LOGIC ARB ${pnl:.4f} | "
                                f"group={event_key[:50]} | sum={total_yes:.4f} edge={edge:.4f}"
                            )
                continue

        threshold_result = _detect_threshold_violations(group)
        if threshold_result:
            # 24-hour cooldown: structural election mispricing persists for weeks;
            # simulates consuming available liquidity at these price levels once per day
            if now_ts - _recently_traded_threshold.get(event_key, 0) < THRESHOLD_COOLDOWN_SEC:
                continue
            m_lower, m_higher, p_lower, p_higher, violation_size = threshold_result
            arbs_found += 1
            _opportunities_this_session += 1

            if wallet.cash < 3.0:
                break

            max_spend = min(wallet.nav * _position_pct(wallet.nav), LOGIC_ARB_MAX_TRADE_USD)
            cost_per_leg = min(wallet.cash * 0.40, max_spend * 0.5)
            no_cost = max(1 - p_higher, 0.01)
            # Cap size so BOTH legs fit within cost_per_leg budget
            size = round(min(
                cost_per_leg / max(p_lower, 0.01),
                cost_per_leg / no_cost,
            ), 2)
            if size < 0.5:
                continue

            actual_cost = round(size * p_lower + size * no_cost, 4)
            net_edge = violation_size - 0.03
            # 50% discount: probabilistic trade, not guaranteed arbitrage
            pnl = round(actual_cost * net_edge * 0.5, 4)

            notes = (
                f"Threshold logic: buy lower_threshold={p_lower:.3f}, "
                f"sell higher_threshold={p_higher:.3f}, violation={violation_size:.3f}"
            )
            if pnl < 0.001:
                continue

            pos = await wallet.open_position(
                market_id=m_lower.id,
                market_question=m_lower.question,
                direction=f"THRESHOLD_HEDGE (violation={violation_size:.3f})",
                cost=actual_cost,
                size=size,
                trade_type=TradeType.HEDGE,
                price=p_lower,
                notes=notes,
                resolution_time=m_lower.end_date,
                leg2_market_id=m_higher.id,
                leg2_question=m_higher.question,
            )
            if pos:
                await wallet.close_position(
                    pos_id=pos.id,
                    pnl=pnl,
                    close_price=p_lower,
                    trade_type=TradeType.CLOSE,
                    notes=f"Threshold arb closed, pnl=${pnl:.3f}"
                )
                _recently_traded_threshold[event_key] = now_ts
                log.info(
                    f"[logic_arb] ✅ THRESHOLD ARB ${pnl:.4f} | "
                    f"{m_lower.question[:50]} / {m_higher.question[:50]}"
                )

    log.info(f"[logic_arb] Scan #{_scan_count} done. Found {arbs_found} opportunities.")
    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(f"[logic_arb] Strategy started. Min edge={LOGIC_ARB_MIN_EDGE}, interval={LOGIC_ARB_SCAN_INTERVAL}s")

    await asyncio.sleep(8)

    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[logic_arb] Scan error: {e}", exc_info=True)
        await asyncio.sleep(LOGIC_ARB_SCAN_INTERVAL)


def stop():
    global _running
    _running = False
