import asyncio
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from app.models import (
    StrategyName, PositionStatus, TradeType,
    PaperTrade, PaperPosition, WalletState
)
from app.config import PAPER_WALLET_INITIAL
from app import database as db

log = logging.getLogger("paper_trader")


class PaperWallet:
    def __init__(self, strategy: StrategyName):
        self.strategy = strategy
        self.initial_balance = PAPER_WALLET_INITIAL
        self.cash = PAPER_WALLET_INITIAL
        self.realized_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.closed_trades = 0
        self.total_opportunities = 0
        self._positions: Dict[str, PaperPosition] = {}
        self._trades: List[PaperTrade] = []
        self._lock = asyncio.Lock()
        self.status = "scanning"
        self.last_scan: Optional[datetime] = None
        self.opportunities_found = 0
        self._opportunity_times: List[datetime] = []

    async def restore(self):
        saved = await db.load_wallet_states()
        if self.strategy.value in saved:
            s = saved[self.strategy.value]
            self.cash = s["cash"]
            self.realized_pnl = s["realized_pnl"]
            self.total_trades = s["total_trades"]
            self.winning_trades = s["winning_trades"]
            self.total_opportunities = s["total_opportunities"]
            self.closed_trades = s.get("closed_trades") or max(s.get("winning_trades", 0), self.total_trades // 2)
        open_pos = await db.load_open_positions(self.strategy.value)
        for p in open_pos:
            rt = p.get("resolution_time")
            resolution_dt = datetime.fromisoformat(rt) if rt else None
            pos = PaperPosition(
                id=p["id"], strategy=self.strategy,
                market_id=p["market_id"], market_question=p["market_question"],
                direction=p["direction"], cost_basis=p["cost_basis"],
                size=p["size"], open_time=datetime.fromisoformat(p["open_time"]),
                status=PositionStatus.OPEN,
                current_value=p.get("current_value", 0),
                resolution_time=resolution_dt,
                notes=p.get("notes", ""),
                leg2_market_id=p.get("leg2_market_id"),
                leg2_question=p.get("leg2_question"),
            )
            self._positions[pos.id] = pos
        recent = await db.load_recent_trades(self.strategy.value, limit=100)
        for t in recent:
            trade = PaperTrade(
                id=t["id"], strategy=self.strategy,
                market_id=t["market_id"], market_question=t["market_question"],
                trade_type=TradeType(t["trade_type"]),
                price=t["price"], size=t["size"], cost=t["cost"],
                timestamp=datetime.fromisoformat(t["timestamp"]),
                position_id=t["position_id"],
                notes=t.get("notes", ""),
                pnl_at_close=t.get("pnl_at_close"),
            )
            self._trades.append(trade)
        log.info(f"[{self.strategy.value}] Restored wallet: cash=${self.cash:.2f}, "
                 f"positions={len(self._positions)}, trades={len(self._trades)}")

    async def _save(self):
        await db.save_wallet_state(
            self.strategy.value, self.cash, self.realized_pnl,
            self.total_trades, self.winning_trades, self.total_opportunities,
            self.closed_trades
        )

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            (p.current_value - p.cost_basis)
            for p in self._positions.values()
            if p.status == PositionStatus.OPEN
        )

    @property
    def nav(self) -> float:
        return self.cash + sum(
            p.current_value for p in self._positions.values()
            if p.status == PositionStatus.OPEN
        )

    @property
    def win_rate(self) -> float:
        if self.closed_trades == 0:
            return 0.0
        return round(self.winning_trades / self.closed_trades * 100, 1)

    @property
    def open_positions(self) -> List[PaperPosition]:
        return [p for p in self._positions.values() if p.status == PositionStatus.OPEN]

    @property
    def recent_trades(self) -> List[PaperTrade]:
        return sorted(self._trades, key=lambda t: t.timestamp, reverse=True)[:50]

    def opportunities_per_hour(self) -> float:
        now = datetime.utcnow()
        self._opportunity_times = [
            t for t in self._opportunity_times
            if (now - t).total_seconds() < 3600
        ]
        return float(len(self._opportunity_times))

    async def open_position(
        self, market_id: str, market_question: str,
        direction: str, cost: float, size: float,
        trade_type: TradeType, price: float,
        notes: str = "",
        resolution_time: Optional[datetime] = None,
        leg2_market_id: Optional[str] = None,
        leg2_question: Optional[str] = None,
    ) -> Optional[PaperPosition]:
        async with self._lock:
            if self.cash < cost:
                log.debug(f"[{self.strategy.value}] Insufficient cash: need ${cost:.2f}, have ${self.cash:.2f}")
                return None
            self.cash -= cost
            pos_id = str(uuid.uuid4())[:12]
            pos = PaperPosition(
                id=pos_id, strategy=self.strategy,
                market_id=market_id, market_question=market_question[:120],
                direction=direction, cost_basis=cost,
                size=size, open_time=datetime.utcnow(),
                status=PositionStatus.OPEN,
                current_value=cost,
                notes=notes,
                resolution_time=resolution_time,
                leg2_market_id=leg2_market_id,
                leg2_question=leg2_question,
            )
            self._positions[pos_id] = pos
            trade = PaperTrade(
                id=str(uuid.uuid4())[:12],
                strategy=self.strategy, market_id=market_id,
                market_question=market_question[:120],
                trade_type=trade_type, price=price, size=size,
                cost=cost, timestamp=datetime.utcnow(),
                position_id=pos_id, notes=notes
            )
            self._trades.append(trade)
            self.total_trades += 1
            self.total_opportunities += 1
            self._opportunity_times.append(datetime.utcnow())
            await db.save_position(self._pos_to_dict(pos))
            await db.save_trade(self._trade_to_dict(trade))
            await self._save()
            log.info(f"[{self.strategy.value}] OPEN pos={pos_id[:8]} {direction} "
                     f"cost=${cost:.3f} size={size:.2f} {market_question[:60]}")
            return pos

    async def close_position(
        self, pos_id: str, pnl: float,
        close_price: float, trade_type: TradeType,
        notes: str = ""
    ) -> Optional[float]:
        async with self._lock:
            pos = self._positions.get(pos_id)
            if not pos or pos.status != PositionStatus.OPEN:
                return None
            pos.status = PositionStatus.CLOSED
            pos.close_time = datetime.utcnow()
            pos.realized_pnl = pnl
            pos.current_value = pos.cost_basis + pnl
            self.cash += pos.cost_basis + pnl
            self.realized_pnl += pnl
            self.total_trades += 1
            self.closed_trades += 1
            if pnl > 0:
                self.winning_trades += 1
            trade = PaperTrade(
                id=str(uuid.uuid4())[:12],
                strategy=self.strategy, market_id=pos.market_id,
                market_question=pos.market_question,
                trade_type=trade_type, price=close_price,
                size=pos.size, cost=-(pos.cost_basis + pnl),
                timestamp=datetime.utcnow(), position_id=pos_id,
                notes=notes, pnl_at_close=pnl
            )
            self._trades.append(trade)
            await db.save_position(self._pos_to_dict(pos))
            await db.save_trade(self._trade_to_dict(trade))
            await self._save()
            log.info(f"[{self.strategy.value}] CLOSE pos={pos_id[:8]} pnl=${pnl:.3f} "
                     f"cash_now=${self.cash:.2f}")
            return pnl

    async def add_lp_reward(self, amount: float, market_id: str, notes: str = "LP reward"):
        async with self._lock:
            self.cash += amount
            self.realized_pnl += amount
            self.winning_trades += 1
            self.closed_trades += 1
            self.total_trades += 1
            trade = PaperTrade(
                id=str(uuid.uuid4())[:12],
                strategy=self.strategy, market_id=market_id,
                market_question="LP Reward Accrual",
                trade_type=TradeType.LP_REWARD,
                price=1.0, size=amount, cost=-amount,
                timestamp=datetime.utcnow(),
                position_id="lp_reward",
                notes=notes, pnl_at_close=amount
            )
            self._trades.append(trade)
            await db.save_trade(self._trade_to_dict(trade))
            await self._save()

    async def update_position_value(self, pos_id: str, current_value: float):
        pos = self._positions.get(pos_id)
        if pos and pos.status == PositionStatus.OPEN:
            pos.current_value = current_value
            await db.save_position(self._pos_to_dict(pos))

    def get_state(self) -> WalletState:
        return WalletState(
            strategy=self.strategy,
            initial_balance=self.initial_balance,
            cash=self.cash,
            unrealized_pnl=self.unrealized_pnl,
            realized_pnl=self.realized_pnl,
            nav=self.nav,
            total_trades=self.total_trades,
            winning_trades=self.winning_trades,
            win_rate=self.win_rate,
            total_opportunities=self.total_opportunities,
            open_positions=len(self.open_positions),
            last_trade_time=self._trades[-1].timestamp if self._trades else None,
        )

    def _pos_to_dict(self, pos: PaperPosition) -> Dict:
        return {
            "id": pos.id, "strategy": pos.strategy.value,
            "market_id": pos.market_id, "market_question": pos.market_question,
            "direction": pos.direction, "cost_basis": pos.cost_basis,
            "size": pos.size, "open_time": pos.open_time.isoformat(),
            "close_time": pos.close_time.isoformat() if pos.close_time else None,
            "status": pos.status.value, "realized_pnl": pos.realized_pnl,
            "current_value": pos.current_value,
            "resolution_time": pos.resolution_time.isoformat() if pos.resolution_time else None,
            "notes": pos.notes, "leg2_market_id": pos.leg2_market_id,
            "leg2_question": pos.leg2_question,
        }

    def _trade_to_dict(self, t: PaperTrade) -> Dict:
        return {
            "id": t.id, "strategy": t.strategy.value,
            "market_id": t.market_id, "market_question": t.market_question,
            "trade_type": t.trade_type.value, "price": t.price,
            "size": t.size, "cost": t.cost,
            "timestamp": t.timestamp.isoformat(), "position_id": t.position_id,
            "notes": t.notes, "pnl_at_close": t.pnl_at_close,
        }

    def positions_as_dicts(self) -> List[Dict]:
        return [self._pos_to_dict(p) for p in self.open_positions]

    def trades_as_dicts(self) -> List[Dict]:
        return [self._trade_to_dict(t) for t in self.recent_trades]
