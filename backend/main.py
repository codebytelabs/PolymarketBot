import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import database as db
from app import market_data as md
from app.config import (
    MARKET_REFRESH_INTERVAL, WS_BROADCAST_INTERVAL,
    PAPER_MODE, LOG_LEVEL, DB_PATH
)
from app.models import StrategyName
from app.paper_trader import PaperWallet
from app import strategy_market_making, strategy_near_certainty, strategy_bs_strike, strategy_daily_updown, strategy_weather

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("main")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = FastAPI(title="PolyBot Paper Trading Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ws_clients: Set[WebSocket] = set()
_start_time = time.time()
_nav_history = []
_wallets: dict[str, PaperWallet] = {}


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


async def broadcast(message: dict):
    dead = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_text(json.dumps(message, default=str))
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


def _build_strategy_metrics(name: str, wallet: PaperWallet, status_fn) -> dict:
    state = wallet.get_state()
    status_info = status_fn()
    total_pnl = state.realized_pnl + state.unrealized_pnl
    pnl_pct = (total_pnl / state.initial_balance * 100) if state.initial_balance else 0
    ops_per_hr = wallet.opportunities_per_hour()
    return {
        "strategy": name,
        "nav": round(state.nav, 4),
        "cash": round(state.cash, 4),
        "unrealized_pnl": round(state.unrealized_pnl, 4),
        "realized_pnl": round(state.realized_pnl, 4),
        "total_pnl": round(total_pnl, 4),
        "pnl_pct": round(pnl_pct, 3),
        "total_trades": state.total_trades,
        "winning_trades": state.winning_trades,
        "win_rate": state.win_rate,
        "open_positions": state.open_positions,
        "total_opportunities": state.total_opportunities,
        "status": getattr(wallet, "status", "idle"),
        "last_scan": status_info.get("last_scan"),
        "opportunities_per_hour": round(ops_per_hr, 1),
        "scan_count": status_info.get("scan_count", 0),
    }


def _build_full_state() -> dict:
    w_mm = _wallets.get("market_making")
    w_nc = _wallets.get("near_certain")
    w_bs = _wallets.get("bs_strike")
    w_ud = _wallets.get("daily_updown")
    w_wt = _wallets.get("weather")

    if not (w_mm and w_nc and w_bs and w_ud and w_wt):
        return {"type": "state_update", "ready": False}

    mm_metrics = _build_strategy_metrics("market_making", w_mm, strategy_market_making.get_status)
    nc_metrics = _build_strategy_metrics("near_certain", w_nc, strategy_near_certainty.get_status)
    bs_metrics = _build_strategy_metrics("bs_strike", w_bs, strategy_bs_strike.get_status)
    ud_metrics = _build_strategy_metrics("daily_updown", w_ud, strategy_daily_updown.get_status)
    wt_metrics = _build_strategy_metrics("weather", w_wt, strategy_weather.get_status)

    nav_point = {
        "timestamp": datetime.utcnow().isoformat(),
        "market_making": mm_metrics["nav"],
        "near_certain": nc_metrics["nav"],
        "bs_strike": bs_metrics["nav"],
        "daily_updown": ud_metrics["nav"],
        "weather": wt_metrics["nav"],
    }
    _nav_history.append(nav_point)
    if len(_nav_history) > 2000:
        _nav_history.pop(0)

    all_positions = (
        [{"strategy": "market_making", **p} for p in w_mm.positions_as_dicts()] +
        [{"strategy": "near_certain", **p} for p in w_nc.positions_as_dicts()] +
        [{"strategy": "bs_strike", **p} for p in w_bs.positions_as_dicts()] +
        [{"strategy": "daily_updown", **p} for p in w_ud.positions_as_dicts()] +
        [{"strategy": "weather", **p} for p in w_wt.positions_as_dicts()]
    )
    all_trades = (
        [{"strategy": "market_making", **t} for t in w_mm.trades_as_dicts()[:20]] +
        [{"strategy": "near_certain", **t} for t in w_nc.trades_as_dicts()[:20]] +
        [{"strategy": "bs_strike", **t} for t in w_bs.trades_as_dicts()[:20]] +
        [{"strategy": "daily_updown", **t} for t in w_ud.trades_as_dicts()[:20]] +
        [{"strategy": "weather", **t} for t in w_wt.trades_as_dicts()[:20]]
    )
    all_trades.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    markets = md.get_markets()
    mm_status = strategy_market_making.get_status()

    return {
        "type": "state_update",
        "ready": True,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": round(time.time() - _start_time),
        "paper_mode": PAPER_MODE,
        "markets_tracked": len(markets),
        "strategies": {
            "market_making": mm_metrics,
            "near_certain": nc_metrics,
            "bs_strike": bs_metrics,
            "daily_updown": ud_metrics,
            "weather": wt_metrics,
        },
        "nav_history": _nav_history[-300:],
        "open_positions": all_positions,
        "recent_trades": all_trades[:60],
        "mm_active_quotes": mm_status.get("active_quotes", 0),
        "mm_lp_deployed": mm_status.get("lp_capital_deployed", 0),
    }


async def ws_broadcast_loop():
    while True:
        try:
            state = _build_full_state()
            if state.get("ready"):
                await db.save_nav_point(
                    ts=state["timestamp"],
                    mm=state["strategies"]["market_making"]["nav"],
                    near_certain=state["strategies"]["near_certain"]["nav"],
                    bs_strike=state["strategies"]["bs_strike"]["nav"],
                    daily_updown=state["strategies"]["daily_updown"]["nav"],
                    weather=state["strategies"]["weather"]["nav"],
                )
            if _ws_clients:
                # Send only the latest delta — frontend accumulates the full history
                state["nav_history"] = _nav_history[-10:]
                await broadcast(state)
        except Exception as e:
            log.error(f"Broadcast loop error: {e}")
        await asyncio.sleep(WS_BROADCAST_INTERVAL)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    log.info(f"WS client connected. Total: {len(_ws_clients)}")
    try:
        # Send full historical NAV from DB so the chart shows lifetime history
        full_history = await db.load_nav_history(limit=50000)
        state = _build_full_state()
        state["nav_history"] = full_history if full_history else _nav_history
        await ws.send_text(json.dumps(state, default=str))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug(f"WS client error: {e}")
    finally:
        _ws_clients.discard(ws)
        log.info(f"WS client disconnected. Total: {len(_ws_clients)}")


@app.get("/api/status")
async def api_status():
    markets = md.get_markets()
    return {
        "running": True,
        "paper_mode": PAPER_MODE,
        "uptime_seconds": round(time.time() - _start_time),
        "markets_tracked": len(markets),
        "ws_clients": len(_ws_clients),
        "strategies": {
            name: w.get_state().__dict__
            for name, w in _wallets.items()
        }
    }


@app.get("/api/trades")
async def api_trades(strategy: str = None, limit: int = 100):
    trades = await db.load_recent_trades(strategy, limit)
    return JSONResponse(trades)


@app.get("/api/positions")
async def api_positions(strategy: str = None):
    positions = await db.load_open_positions(strategy)
    return JSONResponse(positions)


@app.get("/api/nav")
async def api_nav(limit: int = 500):
    history = await db.load_nav_history(limit)
    return JSONResponse(history)


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.on_event("startup")
async def startup():
    log.info("=== PolyBot Paper Trading Engine Starting ===")
    log.info(f"Paper mode: {PAPER_MODE}")
    log.info(f"DB path: {DB_PATH}")

    await db.init_db()
    log.info("Database initialized")

    # Restore in-memory NAV history from DB so it survives restarts
    existing_nav = await db.load_nav_history(limit=50000)
    _nav_history.extend(existing_nav)
    log.info(f"Restored {len(_nav_history)} NAV history points from DB")

    mm_wallet = PaperWallet(StrategyName.MARKET_MAKING)
    nc_wallet = PaperWallet(StrategyName.NEAR_CERTAIN)
    bs_wallet = PaperWallet(StrategyName.BS_STRIKE)
    ud_wallet = PaperWallet(StrategyName.DAILY_UPDOWN)
    wt_wallet = PaperWallet(StrategyName.WEATHER)

    await mm_wallet.restore()
    await nc_wallet.restore()
    await bs_wallet.restore()
    await ud_wallet.restore()
    await wt_wallet.restore()

    _wallets["market_making"] = mm_wallet
    _wallets["near_certain"] = nc_wallet
    _wallets["bs_strike"] = bs_wallet
    _wallets["daily_updown"] = ud_wallet
    _wallets["weather"] = wt_wallet

    asyncio.create_task(md.market_data_loop(MARKET_REFRESH_INTERVAL))
    log.info("Market data loop started")

    # market_making and bs_strike disabled — zero fills / zero candidates
    # asyncio.create_task(strategy_market_making.run(mm_wallet))
    # asyncio.create_task(strategy_bs_strike.run(bs_wallet))
    asyncio.create_task(strategy_near_certainty.run(nc_wallet))
    asyncio.create_task(strategy_daily_updown.run(ud_wallet))
    asyncio.create_task(strategy_weather.run(wt_wallet))
    log.info("Active strategies: NearCert + UpDown + Weather  (MM + BS disabled)")

    asyncio.create_task(ws_broadcast_loop())
    log.info("WebSocket broadcast loop started")

    log.info("=== PolyBot ready! Scanning for opportunities... ===")


@app.on_event("shutdown")
async def shutdown():
    strategy_market_making.stop()
    strategy_near_certainty.stop()
    strategy_bs_strike.stop()
    strategy_daily_updown.stop()
    strategy_weather.stop()
    await md.close_session()
    log.info("PolyBot shutdown complete")
