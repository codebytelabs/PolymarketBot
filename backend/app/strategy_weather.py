"""
Weather Forecast Strategy
=========================
Uses free Open-Meteo API (https://open-meteo.com) to get ensemble weather forecasts
and compares them to Polymarket weather market prices.

When GFS/Open-Meteo says probability is 85% but Polymarket prices it at 50%,
we have a 35% edge. We bet using quarter-Kelly criterion for safe compounding.

Strategy logic:
  1. Scan Polymarket for temperature / rain / weather markets
  2. Parse city, threshold, metric, date from question text
  3. Fetch Open-Meteo forecast for that city/date
  4. Compute forecast probability P(event) via normal distribution
  5. If |P_forecast - P_market| >= WEATHER_MIN_EDGE → enter position
  6. Size using quarter-Kelly: f = 0.25 × (p - q) / (1 - q)
  7. Close when market expires (near resolution)

Documented real-world results: $300 → $101K in 2 months (Reddit r/PredictionTrading)
"""

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp

from app.models import StrategyName, TradeType, PositionStatus
from app.paper_trader import PaperWallet
from app import market_data as md
from app.config import (
    WEATHER_SCAN_INTERVAL, WEATHER_MIN_EDGE,
    WEATHER_POSITION_PCT, WEATHER_MAX_CAPITAL_USD,
    WEATHER_KELLY_FRACTION, WEATHER_MAX_POSITIONS,
    GAMMA_API,
)

log = logging.getLogger("strategy.weather")

_wallet: Optional[PaperWallet] = None
_running = False
_last_scan: Optional[datetime] = None
_scan_count = 0
_opportunities_this_session = 0
_recently_traded: Dict[str, float] = {}
TRADE_COOLDOWN_SEC = 3600.0  # 1 hour — weather markets don't reprice that fast

# Major city coordinates (lat, lon) for Open-Meteo lookups
_CITY_COORDS: Dict[str, Tuple[float, float]] = {
    "new york":       (40.71, -74.01),
    "nyc":            (40.71, -74.01),
    "los angeles":    (34.05, -118.24),
    "la":             (34.05, -118.24),
    "chicago":        (41.88, -87.63),
    "houston":        (29.76, -95.37),
    "phoenix":        (33.45, -112.07),
    "miami":          (25.77, -80.19),
    "dallas":         (32.78, -96.80),
    "atlanta":        (33.75, -84.39),
    "seattle":        (47.61, -122.33),
    "denver":         (39.74, -104.98),
    "boston":          (42.36, -71.06),
    "las vegas":      (36.17, -115.14),
    "washington":     (38.91, -77.04),
    "dc":             (38.91, -77.04),
    "san francisco":  (37.77, -122.42),
    "london":         (51.51, -0.13),
    "paris":          (48.86, 2.35),
    "tokyo":          (35.68, 139.69),
    "sydney":         (-33.87, 151.21),
    "cape town":      (-33.92, 18.42),
    "seoul":          (37.57, 126.98),
    "moscow":         (55.76, 37.62),
    "sao paulo":      (-23.55, -46.63),
    "são paulo":      (-23.55, -46.63),
    "chengdu":        (30.57, 104.07),
    "hong kong":      (22.32, 114.17),
    "kuala lumpur":   (3.14, 101.69),
    "mumbai":         (19.08, 72.88),
    "delhi":          (28.61, 77.21),
    "new delhi":      (28.61, 77.21),
    "dubai":          (25.20, 55.27),
    "singapore":      (1.35, 103.82),
    "berlin":         (52.52, 13.41),
    "rome":           (41.90, 12.50),
    "madrid":         (40.42, -3.70),
    "toronto":        (43.65, -79.38),
    "mexico city":    (19.43, -99.13),
    "buenos aires":   (-34.60, -58.38),
    "cairo":          (30.04, 31.24),
    "bangkok":        (13.76, 100.50),
    "shanghai":       (31.23, 121.47),
    "beijing":        (39.90, 116.41),
    "jakarta":        (-6.21, 106.85),
    "lagos":          (6.52, 3.38),
    "nairobi":        (-1.29, 36.82),
    "istanbul":       (41.01, 28.98),
    "riyadh":         (24.69, 46.72),
    "johannesburg":   (-26.20, 28.05),
    "manila":         (14.60, 120.98),
    "lima":           (-12.05, -77.04),
    "bogota":         (4.71, -74.07),
    "santiago":       (-33.45, -70.67),
    "zurich":         (47.37, 8.54),
    "amsterdam":      (52.37, 4.90),
    "vienna":         (48.21, 16.37),
    "stockholm":      (59.33, 18.07),
    "oslo":           (59.91, 10.75),
    "warsaw":         (52.23, 21.01),
    "prague":         (50.08, 14.44),
    "taipei":         (25.03, 121.57),
    "ho chi minh":    (10.82, 106.63),
    "hanoi":          (21.03, 105.85),
    "melbourne":      (-37.81, 144.96),
    "auckland":       (-36.85, 174.76),
    "vancouver":      (49.28, -123.12),
    "montreal":       (45.50, -73.57),
    "san diego":      (32.72, -117.16),
    "portland":       (45.52, -122.68),
    "minneapolis":    (44.98, -93.27),
    "detroit":        (42.33, -83.05),
    "philadelphia":   (39.95, -75.17),
    "nashville":      (36.16, -86.78),
    "austin":         (30.27, -97.74),
    "charlotte":      (35.23, -80.84),
    "salt lake city": (40.76, -111.89),
    "st louis":       (38.63, -90.20),
    "kansas city":    (39.10, -94.58),
    "columbus":       (39.96, -82.99),
    "indianapolis":   (39.77, -86.16),
    "san antonio":    (29.42, -98.49),
    "jacksonville":   (30.33, -81.66),
    "tampa":          (27.95, -82.46),
    "orlando":        (28.54, -81.38),
    "raleigh":        (35.78, -78.64),
    "pittsburgh":     (40.44, -79.99),
    "cincinnati":     (39.10, -84.51),
    "milwaukee":      (43.04, -87.91),
    "oklahoma city":  (35.47, -97.52),
    "memphis":        (35.15, -90.05),
    "anchorage":      (61.22, -149.90),
    "honolulu":       (21.31, -157.86),
}

# Weather keywords that identify weather markets
_WEATHER_KEYWORDS = [
    "temperature", "temp", "degrees", "fahrenheit", "celsius",
    "°f", "°c",
    "rain", "rainfall", "precipitation", "snow", "snowfall",
    "high of", "low of", "highest temperature", "lowest temperature",
    "hurricane", "tropical storm", "cyclone",
    "heat wave", "cold snap", "freeze",
]


def _is_weather_market(m) -> bool:
    q = m.question.lower()
    return any(kw in q for kw in _WEATHER_KEYWORDS)


def _parse_city(question: str) -> Optional[str]:
    """Extract city from market question."""
    q = question.lower()
    for city in sorted(_CITY_COORDS.keys(), key=len, reverse=True):
        if city in q:
            return city
    return None


def _parse_temperature_threshold(question: str) -> Optional[Tuple[float, str, bool]]:
    """
    Parse temperature threshold and direction from question.
    Returns (threshold, direction, is_celsius).
    
    Examples:
      "will the highest temperature in cape town be 15°c or below" → (15, "below", True)
      "will the highest temperature in atlanta be 73°f or below"  → (73, "below", False)
      "will the highest temperature in seoul be 20°c on april 14" → (20, "exact", True)
    """
    q = question.lower()
    is_celsius = "°c" in q or "celsius" in q
    
    # Pattern 1: "be X°C or below" / "be X°F or below"
    m = re.search(r'be\s+(\d+(?:\.\d+)?)\s*°[cf]\s+or\s+below', q)
    if m:
        val = float(m.group(1))
        return (val, "below", is_celsius)
    
    # Pattern 2: "be X°C or above" / "be X°F or above"
    m = re.search(r'be\s+(\d+(?:\.\d+)?)\s*°[cf]\s+or\s+above', q)
    if m:
        val = float(m.group(1))
        return (val, "above", is_celsius)
    
    # Pattern 3: "be X°C on" (exact — market resolves YES if temp IS exactly X)
    m = re.search(r'be\s+(\d+(?:\.\d+)?)\s*°[cf]\s+on', q)
    if m:
        val = float(m.group(1))
        return (val, "exact", is_celsius)
    
    # Pattern 4: "above $X" / "exceed X" / "over X degrees"
    above_patterns = [
        r'(?:above|exceed|over|more than|higher than)\s+(\d+(?:\.\d+)?)\s*(?:°f|°c|f|c|degrees?)?',
        r'high(?:s?)\s+(?:of\s+)?(\d+(?:\.\d+)?)\+?',
    ]
    for pat in above_patterns:
        m = re.search(pat, q)
        if m:
            val = float(m.group(1))
            return (val, "above", is_celsius)
    
    # Pattern 5: "below X"
    m = re.search(r'(?:below|under|less than|lower than)\s+(\d+(?:\.\d+)?)\s*(?:°f|°c|f|c|degrees?)?', q)
    if m:
        val = float(m.group(1))
        return (val, "below", is_celsius)
    
    return None


def _parse_target_date(question: str, market_end: Optional[datetime]) -> Optional[datetime]:
    """Try to extract the target date from the question or use market end date."""
    q = question.lower()
    today = datetime.now(timezone.utc)

    # Look for explicit day offsets
    if "today" in q:
        return today
    if "tomorrow" in q:
        return today + timedelta(days=1)
    if "this week" in q:
        return today + timedelta(days=3)

    # Use market end date as a proxy for the target date
    if market_end:
        end = market_end if market_end.tzinfo else market_end.replace(tzinfo=timezone.utc)
        return end

    return today + timedelta(days=1)


async def _fetch_forecast(city: str, target_date: datetime) -> Optional[Dict]:
    """
    Fetch Open-Meteo daily forecast for the given city and date.
    Returns dict with temperature_max, temperature_min, precipitation_probability_max.
    """
    lat, lon = _CITY_COORDS[city]
    days_ahead = max(0, (target_date.date() - datetime.now(timezone.utc).date()).days)
    forecast_days = min(max(days_ahead + 2, 3), 16)

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
        f"precipitation_sum,windspeed_10m_max"
        f"&temperature_unit=fahrenheit"
        f"&timezone=auto"
        f"&forecast_days={forecast_days}"
    )

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        target_str = target_date.strftime("%Y-%m-%d")

        # Find the closest date
        idx = None
        for i, d in enumerate(dates):
            if d == target_str:
                idx = i
                break
        if idx is None and dates:
            idx = min(len(dates) - 1, days_ahead)

        if idx is None:
            return None

        return {
            "date": dates[idx] if idx < len(dates) else target_str,
            "temp_max": (daily.get("temperature_2m_max") or [None])[idx],
            "temp_min": (daily.get("temperature_2m_min") or [None])[idx],
            "precip_prob": (daily.get("precipitation_probability_max") or [None])[idx],
            "precip_sum": (daily.get("precipitation_sum") or [None])[idx],
        }
    except Exception as e:
        log.debug(f"[weather] Open-Meteo fetch error for {city}: {e}")
        return None


def _compute_temperature_probability(
    threshold: float, direction: str, is_celsius: bool,
    temp_max_f: Optional[float], temp_min_f: Optional[float]
) -> Optional[float]:
    """
    Estimate P(temp crosses threshold) using a normal distribution.
    Open-Meteo returns temps in Fahrenheit. If market threshold is Celsius, convert.
    std_dev = 3°F for next-day, 5°F for farther out.
    """
    if temp_max_f is None or temp_min_f is None:
        return None

    # Convert threshold to Fahrenheit for comparison
    thresh_f = threshold * 9.0 / 5.0 + 32.0 if is_celsius else threshold

    # "highest temperature" markets → compare against temp_max
    forecast_center = temp_max_f
    std_dev = 3.5  # conservative ±3.5°F

    z = (thresh_f - forecast_center) / std_dev
    cdf = 0.5 * math.erfc(-z / math.sqrt(2))

    if direction == "above":
        prob = 1.0 - cdf   # P(temp_max > threshold)
    elif direction == "below":
        prob = cdf          # P(temp_max <= threshold)
    elif direction == "exact":
        # P(temp rounds to exactly X): use a ±0.5 degree window
        z_lo = (thresh_f - 0.5 - forecast_center) / std_dev
        z_hi = (thresh_f + 0.5 - forecast_center) / std_dev
        cdf_lo = 0.5 * math.erfc(-z_lo / math.sqrt(2))
        cdf_hi = 0.5 * math.erfc(-z_hi / math.sqrt(2))
        prob = cdf_hi - cdf_lo
    else:
        return None

    return round(max(0.02, min(0.98, prob)), 4)


def _kelly_size(p_forecast: float, p_market: float, nav: float) -> float:
    """
    Quarter-Kelly position sizing for binary prediction market.
    f* = (p - q) / (1 - q)  where q = market price, p = true probability.
    Returns dollar amount to bet.
    """
    if p_forecast <= p_market:
        return 0.0
    kelly_full = (p_forecast - p_market) / (1.0 - p_market)
    kelly_fraction = WEATHER_KELLY_FRACTION * kelly_full
    dollar_size = min(
        nav * min(kelly_fraction, WEATHER_POSITION_PCT),
        WEATHER_MAX_CAPITAL_USD,
    )
    return max(0.0, round(dollar_size, 2))


def get_status() -> Dict:
    return {
        "running": _running,
        "last_scan": _last_scan.isoformat() if _last_scan else None,
        "scan_count": _scan_count,
        "opportunities_this_session": _opportunities_this_session,
        "scan_interval_sec": WEATHER_SCAN_INTERVAL,
        "min_edge": WEATHER_MIN_EDGE,
    }


def stop():
    global _running
    _running = False


def get_wallet() -> Optional[PaperWallet]:
    return _wallet


async def _fetch_resolution(market_id: str) -> Optional[str]:
    """Query Gamma API for a resolved market. Returns 'YES', 'NO', or None if unknown."""
    import json as _json
    session = await md.get_session()
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            # outcomePrices resolves to ["1","0"] for YES win or ["0","1"] for NO win
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
            # Fallback: check winner field
            winner = data.get("winner", "") or ""
            if winner.upper() in ("YES", "NO"):
                return winner.upper()
    except Exception as e:
        log.debug(f"[weather] Resolution fetch error for {market_id}: {e}")
    return None


async def _close_positions(wallet: PaperWallet):
    markets = md.get_markets()
    now = datetime.now(timezone.utc)

    for pos in list(wallet.open_positions):
        if pos.strategy != StrategyName.WEATHER:
            continue

        market = markets.get(pos.market_id)
        close_reason = None
        close_price = 0.5
        is_yes = "BUY_YES" in pos.direction

        if not market:
            # Market gone — query Gamma API for actual resolution outcome
            resolution = await _fetch_resolution(pos.market_id)
            if resolution is None:
                # Can't determine yet, skip and retry next scan
                log.debug(f"[weather] Resolution unknown for {pos.market_id[:12]}, retrying next scan")
                continue
            yes_resolved = (resolution == "YES")
            # We win if: BUY_YES and YES resolved, or BUY_NO and NO resolved
            we_won = (is_yes == yes_resolved)
            close_price = 0.99 if we_won else 0.01
            close_reason = f"resolved_{resolution}_{'WIN' if we_won else 'LOSS'}"
        else:
            end = market.end_date
            if end:
                end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
                secs_left = (end - now).total_seconds()

                if secs_left <= 0:
                    # Expired and still in market list — close at live bid
                    close_price = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
                    close_price = max(close_price, 0.01)
                    close_reason = f"expired secs={secs_left:.0f}"
                elif secs_left <= 3600:
                    # < 1 hour left: lock in any movement at live market bid
                    close_price = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
                    close_price = max(close_price, 0.01)
                    close_reason = f"near_expiry {secs_left/3600:.1f}h"

        if not close_reason:
            continue

        cost_per_token = pos.cost_basis / pos.size if pos.size else 0
        pnl = round((close_price - cost_per_token) * pos.size, 5)
        tt = TradeType.SELL_YES if is_yes else TradeType.SELL_NO
        await wallet.close_position(pos.id, pnl, close_price, tt, notes=f"Weather close: {close_reason}")
        log.info(f"[weather] 📤 CLOSE {close_reason} pnl=${pnl:.4f} | {pos.market_question[:55]}")


async def _update_marks(wallet: PaperWallet):
    markets = md.get_markets()
    for pos in wallet.open_positions:
        if pos.strategy != StrategyName.WEATHER:
            continue
        market = markets.get(pos.market_id)
        if not market:
            continue
        is_yes = "BUY_YES" in pos.direction
        bid = market.yes_best_bid if is_yes else max(1 - market.yes_best_ask, 0.01)
        new_value = round(pos.size * max(bid, 0.01), 4)
        await wallet.update_position_value(pos.id, new_value)


async def scan_once(wallet: PaperWallet):
    global _last_scan, _scan_count, _opportunities_this_session

    markets = md.get_markets()
    if not markets:
        return

    _last_scan = datetime.utcnow()
    _scan_count += 1
    await _close_positions(wallet)
    await _update_marks(wallet)

    wallet.last_scan = _last_scan
    wallet.status = "scanning"

    now_ts = time.time()
    weather_markets = [
        m for m in markets.values()
        if _is_weather_market(m)
        and now_ts - _recently_traded.get(m.id, 0) > TRADE_COOLDOWN_SEC
        and m.yes_best_ask > 0
        and m.yes_best_bid > 0
    ]

    log.info(
        f"[weather] Scan #{_scan_count}: {len(markets)} markets → "
        f"{len(weather_markets)} weather markets to analyze"
    )

    for m in weather_markets[:40]:  # scan up to 40 weather markets per cycle
        city = _parse_city(m.question)
        if not city:
            continue

        temp_result = _parse_temperature_threshold(m.question)
        if not temp_result:
            continue

        threshold, direction, is_celsius = temp_result
        target_date = _parse_target_date(m.question, m.end_date)
        if not target_date:
            continue

        # Don't trade if market expires in <1 hour (too late)
        now = datetime.now(timezone.utc)
        if m.end_date:
            end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
            hours_left = (end - now).total_seconds() / 3600.0
            if hours_left < 1.0:
                continue

        forecast = await _fetch_forecast(city, target_date)
        if not forecast:
            log.debug(f"[weather] No forecast for {city} on {target_date.date()}")
            continue

        p_forecast = _compute_temperature_probability(
            threshold, direction, is_celsius,
            forecast.get("temp_max"),
            forecast.get("temp_min"),
        )
        if p_forecast is None:
            continue

        # Market price = mid of YES
        p_market = m.mid if m.mid > 0 else (m.yes_best_bid + m.yes_best_ask) / 2.0
        edge = p_forecast - p_market
        abs_edge = abs(edge)

        if abs_edge < WEATHER_MIN_EDGE:
            log.debug(
                f"[weather] Edge too small: forecast={p_forecast:.3f} market={p_market:.3f} "
                f"edge={edge:.3f} | {m.question[:60]}"
            )
            continue

        # Determine direction: buy YES if forecast > market, buy NO if forecast < market
        if edge > 0:
            # Forecast says MORE likely than market → buy YES
            bet_direction = "BUY_YES"
            entry_price = m.yes_best_ask
            trade_type = TradeType.BUY_YES
        else:
            # Forecast says LESS likely than market → buy NO (buy YES on NO token)
            bet_direction = "BUY_NO"
            entry_price = m.no_best_ask
            trade_type = TradeType.BUY_NO
            edge = -edge  # positive edge for sizing

        if entry_price <= 0 or entry_price >= 1.0:
            continue

        open_count = sum(1 for p in wallet.open_positions if p.strategy == StrategyName.WEATHER)
        if open_count >= WEATHER_MAX_POSITIONS:
            break

        if wallet.cash < 2.0:
            break

        dollar_size = _kelly_size(
            p_forecast if bet_direction == "BUY_YES" else (1 - p_forecast),
            p_market if bet_direction == "BUY_YES" else (1 - p_market),
            wallet.nav,
        )

        if dollar_size < 1.0:
            continue

        dollar_size = min(dollar_size, wallet.cash * 0.9)
        token_size = round(dollar_size / entry_price, 4)
        cost = round(token_size * entry_price, 4)

        # Expected PnL: if we're right, the token resolves to $1
        # Expected value = token_size × p_forecast - cost
        expected_win = round(token_size * (p_forecast if bet_direction == "BUY_YES" else (1 - p_forecast)), 4)
        expected_pnl = round(expected_win - cost, 5)

        if expected_pnl <= 0:
            continue

        notes = (
            f"Weather {bet_direction}: city={city} threshold={threshold:.1f}F {direction} "
            f"forecast={p_forecast:.3f} market={p_market:.3f} edge={abs_edge:.3f} "
            f"kelly={WEATHER_KELLY_FRACTION}× "
            f"forecast_hi={forecast.get('temp_max')} forecast_lo={forecast.get('temp_min')}"
        )

        pos = await wallet.open_position(
            market_id=m.id,
            market_question=m.question,
            direction=bet_direction,
            cost=cost,
            size=token_size,
            trade_type=trade_type,
            price=entry_price,
            notes=notes,
            resolution_time=m.end_date,
        )

        if pos:
            _recently_traded[m.id] = now_ts
            _opportunities_this_session += 1
            log.info(
                f"[weather] 📥 ENTERED {bet_direction} edge={abs_edge:.3f} cost=${cost:.2f} | "
                f"city={city} threshold={threshold:.0f} {direction} "
                f"forecast={p_forecast:.3f} market={p_market:.3f} | "
                f"{m.question[:55]}"
            )

    wallet.status = "idle"


async def run(wallet: PaperWallet):
    global _wallet, _running
    _wallet = wallet
    _running = True
    log.info(
        f"[weather] Strategy started. "
        f"Min edge={WEATHER_MIN_EDGE}, interval={WEATHER_SCAN_INTERVAL}s, "
        f"Kelly fraction={WEATHER_KELLY_FRACTION}"
    )

    # Wait for market data and initial scan to settle
    await asyncio.sleep(20)

    while _running:
        try:
            await scan_once(wallet)
        except Exception as e:
            log.error(f"[weather] Scan error: {e}", exc_info=True)
        await asyncio.sleep(WEATHER_SCAN_INTERVAL)
