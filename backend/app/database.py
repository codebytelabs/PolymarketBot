import aiosqlite
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                market_id TEXT NOT NULL,
                market_question TEXT,
                trade_type TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                cost REAL NOT NULL,
                timestamp TEXT NOT NULL,
                position_id TEXT,
                notes TEXT,
                pnl_at_close REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                market_id TEXT NOT NULL,
                market_question TEXT,
                direction TEXT,
                cost_basis REAL NOT NULL,
                size REAL NOT NULL,
                open_time TEXT NOT NULL,
                close_time TEXT,
                status TEXT NOT NULL,
                realized_pnl REAL,
                current_value REAL,
                resolution_time TEXT,
                notes TEXT,
                leg2_market_id TEXT,
                leg2_question TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS nav_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_making REAL NOT NULL DEFAULT 100.0,
                near_certain REAL NOT NULL DEFAULT 100.0,
                bs_strike REAL NOT NULL DEFAULT 100.0,
                daily_updown REAL NOT NULL DEFAULT 100.0,
                weather REAL NOT NULL DEFAULT 100.0
            )
        """)
        for col in ("bs_strike", "daily_updown", "weather"):
            try:
                await db.execute(f"ALTER TABLE nav_history ADD COLUMN {col} REAL NOT NULL DEFAULT 100.0")
                await db.commit()
            except Exception:
                pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallet_state (
                strategy TEXT PRIMARY KEY,
                cash REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                total_trades INTEGER NOT NULL,
                winning_trades INTEGER NOT NULL,
                total_opportunities INTEGER NOT NULL,
                closed_trades INTEGER NOT NULL DEFAULT 0
            )
        """)
        try:
            await db.execute("ALTER TABLE wallet_state ADD COLUMN closed_trades INTEGER NOT NULL DEFAULT 0")
            await db.commit()
        except Exception:
            pass
        await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_positions_strategy ON positions(strategy)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_nav_timestamp ON nav_history(timestamp)")
        await db.commit()


async def save_trade(trade: Dict[str, Any]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO trades
            (id, strategy, market_id, market_question, trade_type, price, size, cost, timestamp, position_id, notes, pnl_at_close)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trade["id"], trade["strategy"], trade["market_id"], trade["market_question"],
            trade["trade_type"], trade["price"], trade["size"], trade["cost"],
            trade["timestamp"], trade["position_id"], trade.get("notes", ""), trade.get("pnl_at_close")
        ))
        await db.commit()


async def save_position(pos: Dict[str, Any]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO positions
            (id, strategy, market_id, market_question, direction, cost_basis, size, open_time,
             close_time, status, realized_pnl, current_value, resolution_time, notes, leg2_market_id, leg2_question)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pos["id"], pos["strategy"], pos["market_id"], pos["market_question"],
            pos["direction"], pos["cost_basis"], pos["size"], pos["open_time"],
            pos.get("close_time"), pos["status"], pos.get("realized_pnl"),
            pos.get("current_value", 0), pos.get("resolution_time"),
            pos.get("notes", ""), pos.get("leg2_market_id"), pos.get("leg2_question")
        ))
        await db.commit()


async def save_nav_point(ts: str, mm: float, near_certain: float = 100.0,
                          bs_strike: float = 100.0, daily_updown: float = 100.0,
                          weather: float = 100.0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO nav_history (timestamp, market_making, near_certain, bs_strike, daily_updown, weather) VALUES (?,?,?,?,?,?)",
            (ts, mm, near_certain, bs_strike, daily_updown, weather)
        )
        await db.commit()


async def load_recent_trades(strategy: Optional[str] = None, limit: int = 50) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if strategy:
            cursor = await db.execute(
                "SELECT * FROM trades WHERE strategy=? ORDER BY timestamp DESC LIMIT ?",
                (strategy, limit)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def load_open_positions(strategy: Optional[str] = None) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if strategy:
            cursor = await db.execute(
                "SELECT * FROM positions WHERE strategy=? AND status='open' ORDER BY open_time DESC",
                (strategy,)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY open_time DESC"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def load_nav_history(limit: int = 500) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT timestamp, market_making, near_certain, bs_strike, daily_updown, weather FROM nav_history ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return list(reversed([dict(r) for r in rows]))


async def save_wallet_state(strategy: str, cash: float, realized_pnl: float,
                             total_trades: int, winning_trades: int, total_opportunities: int,
                             closed_trades: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO wallet_state
            (strategy, cash, realized_pnl, total_trades, winning_trades, total_opportunities, closed_trades)
            VALUES (?,?,?,?,?,?,?)
        """, (strategy, cash, realized_pnl, total_trades, winning_trades, total_opportunities, closed_trades))
        await db.commit()


async def load_wallet_states() -> Dict[str, Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM wallet_state")
        rows = await cursor.fetchall()
        return {r["strategy"]: dict(r) for r in rows}
