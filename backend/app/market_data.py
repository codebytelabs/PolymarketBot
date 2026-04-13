import asyncio
import aiohttp
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dateutil import parser as dateparser

from app.config import GAMMA_API, CLOB_API, MAX_MARKETS_TO_SCAN, MIN_MARKET_VOLUME
from app.models import MarketInfo

log = logging.getLogger("market_data")

_markets: Dict[str, MarketInfo] = {}
_session: Optional[aiohttp.ClientSession] = None


def get_markets() -> Dict[str, MarketInfo]:
    return _markets


def get_market(market_id: str) -> Optional[MarketInfo]:
    return _markets.get(market_id)


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=10)
        _session = aiohttp.ClientSession(timeout=timeout)
    return _session


async def fetch_markets() -> List[Dict]:
    session = await get_session()
    all_markets = []
    offset = 0
    limit = 100
    while len(all_markets) < MAX_MARKETS_TO_SCAN:
        try:
            url = (
                f"{GAMMA_API}/markets"
                f"?active=true&closed=false&limit={limit}&offset={offset}"
                f"&order=volume&ascending=false"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not data:
                    break
                all_markets.extend(data)
                if len(data) < limit:
                    break
                offset += limit
        except Exception as e:
            log.warning(f"Gamma API fetch error at offset {offset}: {e}")
            break
    return all_markets


async def fetch_order_book(token_id: str) -> Optional[Dict]:
    session = await get_session()
    try:
        url = f"{CLOB_API}/book?token_id={token_id}"
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        log.debug(f"Order book fetch error for {token_id}: {e}")
    return None


def parse_best_ask(book: Optional[Dict]) -> float:
    if not book or not book.get("asks"):
        return 1.0
    try:
        asks = sorted(book["asks"], key=lambda x: float(x.get("price", 1)))
        return float(asks[0]["price"])
    except Exception:
        return 1.0


def parse_best_bid(book: Optional[Dict]) -> float:
    if not book or not book.get("bids"):
        return 0.0
    try:
        bids = sorted(book["bids"], key=lambda x: float(x.get("price", 0)), reverse=True)
        return float(bids[0]["price"])
    except Exception:
        return 0.0


async def enrich_market_with_orderbook(market: MarketInfo) -> MarketInfo:
    yes_book, no_book = await asyncio.gather(
        fetch_order_book(market.yes_token_id),
        fetch_order_book(market.no_token_id),
        return_exceptions=True
    )
    if isinstance(yes_book, Exception):
        yes_book = None
    if isinstance(no_book, Exception):
        no_book = None

    market.yes_best_ask = parse_best_ask(yes_book)
    market.no_best_ask = parse_best_ask(no_book)
    market.yes_best_bid = parse_best_bid(yes_book)
    market.no_best_bid = parse_best_bid(no_book)

    if market.yes_best_bid > 0 and market.yes_best_ask < 1:
        market.mid = (market.yes_best_bid + market.yes_best_ask) / 2
        market.spread = market.yes_best_ask - market.yes_best_bid
    else:
        try:
            market.mid = float(market.yes_price) if market.yes_price else 0.5
        except Exception:
            market.mid = 0.5
        market.spread = 0.0

    market.last_updated = datetime.utcnow()
    return market


def _derive_event_slug(raw: Dict) -> str:
    raw_slug = raw.get("slug", "") or ""
    group_item = raw.get("groupItemTitle", "") or ""
    event_slug_explicit = raw.get("eventSlug", "") or ""
    group_slug_explicit = raw.get("groupSlug", "") or ""

    if event_slug_explicit:
        return event_slug_explicit
    if group_slug_explicit:
        return group_slug_explicit

    if group_item and raw_slug:
        normalized = re.sub(r"[^a-z0-9]+", "-", group_item.lower()).strip("-")
        if normalized and normalized in raw_slug:
            event_key = raw_slug.replace(f"-{normalized}", "").replace(f"{normalized}-", "")
            event_key = re.sub(r"-+", "-", event_key).strip("-")
            if len(event_key) > 5:
                return event_key

    return raw.get("category", "") or raw_slug


def parse_market(raw: Dict) -> Optional[MarketInfo]:
    try:
        outcomes = raw.get("outcomes", [])
        clob_ids = raw.get("clobTokenIds", [])
        outcome_prices = raw.get("outcomePrices", [])

        if not clob_ids or len(clob_ids) < 2:
            return None
        if not isinstance(clob_ids, list):
            import json
            try:
                clob_ids = json.loads(clob_ids)
            except Exception:
                return None

        volume = float(raw.get("volume", 0) or 0)
        if volume < MIN_MARKET_VOLUME:
            return None

        yes_price = 0.5
        no_price = 0.5
        if outcome_prices:
            try:
                if isinstance(outcome_prices, str):
                    import json
                    outcome_prices = json.loads(outcome_prices)
                yes_price = float(outcome_prices[0])
                no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 1 - yes_price
            except Exception:
                pass

        end_date = None
        if raw.get("endDate"):
            try:
                end_date = dateparser.parse(raw["endDate"])
            except Exception:
                pass

        market_id = str(raw.get("id") or raw.get("conditionId", ""))
        if not market_id:
            return None

        return MarketInfo(
            id=market_id,
            question=raw.get("question", "Unknown")[:200],
            condition_id=raw.get("conditionId", ""),
            yes_token_id=str(clob_ids[0]),
            no_token_id=str(clob_ids[1]),
            yes_price=yes_price,
            no_price=no_price,
            volume=volume,
            end_date=end_date,
            event_slug=_derive_event_slug(raw),
            category=raw.get("category", ""),
        )
    except Exception as e:
        log.debug(f"Market parse error: {e}")
        return None


async def refresh_markets():
    global _markets
    log.info("Refreshing market list from Gamma API...")
    raw_markets = await fetch_markets()
    parsed = []
    for raw in raw_markets:
        m = parse_market(raw)
        if m:
            parsed.append(m)
    log.info(f"Parsed {len(parsed)} eligible markets (volume >= ${MIN_MARKET_VOLUME})")

    enriched_count = 0
    semaphore = asyncio.Semaphore(15)

    async def enrich_with_sem(m: MarketInfo) -> MarketInfo:
        async with semaphore:
            return await enrich_market_with_orderbook(m)

    tasks = [enrich_with_sem(m) for m in parsed[:MAX_MARKETS_TO_SCAN]]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    new_markets: Dict[str, MarketInfo] = {}
    for r in results:
        if isinstance(r, MarketInfo):
            new_markets[r.id] = r
            enriched_count += 1

    _markets = new_markets
    log.info(f"Market refresh done: {enriched_count} markets with order books")
    return enriched_count


async def refresh_orderbooks_for_subset(market_ids: List[str]):
    semaphore = asyncio.Semaphore(10)

    async def refresh_one(mid: str):
        async with semaphore:
            m = _markets.get(mid)
            if m:
                await enrich_market_with_orderbook(m)

    await asyncio.gather(*[refresh_one(mid) for mid in market_ids], return_exceptions=True)


async def market_data_loop(refresh_interval: float = 30.0):
    while True:
        try:
            await refresh_markets()
        except Exception as e:
            log.error(f"Market refresh loop error: {e}")
        await asyncio.sleep(refresh_interval)


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
