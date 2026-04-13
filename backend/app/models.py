from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class StrategyName(str, Enum):
    INTRA_ARB = "intra_arb"
    LOGIC_ARB = "logic_arb"
    MARKET_MAKING = "market_making"
    WEATHER = "weather"
    CRYPTO_MM = "crypto_mm"
    NEAR_CERTAIN = "near_certain"
    BS_STRIKE = "bs_strike"
    DAILY_UPDOWN = "daily_updown"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"


class TradeType(str, Enum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    SELL_YES = "SELL_YES"
    SELL_NO = "SELL_NO"
    BUY_BOTH = "BUY_BOTH"
    HEDGE = "HEDGE"
    MM_BID = "MM_BID"
    MM_ASK = "MM_ASK"
    LP_REWARD = "LP_REWARD"
    CLOSE = "CLOSE"


@dataclass
class MarketInfo:
    id: str
    question: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume: float
    end_date: Optional[datetime]
    event_slug: Optional[str]
    category: Optional[str]
    yes_best_ask: float = 0.0
    no_best_ask: float = 0.0
    yes_best_bid: float = 0.0
    no_best_bid: float = 0.0
    spread: float = 0.0
    mid: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PaperTrade:
    id: str
    strategy: StrategyName
    market_id: str
    market_question: str
    trade_type: TradeType
    price: float
    size: float
    cost: float
    timestamp: datetime
    position_id: str
    notes: str = ""
    pnl_at_close: Optional[float] = None


@dataclass
class PaperPosition:
    id: str
    strategy: StrategyName
    market_id: str
    market_question: str
    direction: str
    cost_basis: float
    size: float
    open_time: datetime
    status: PositionStatus
    close_time: Optional[datetime] = None
    realized_pnl: Optional[float] = None
    current_value: float = 0.0
    resolution_time: Optional[datetime] = None
    notes: str = ""
    leg2_market_id: Optional[str] = None
    leg2_question: Optional[str] = None


@dataclass
class WalletState:
    strategy: StrategyName
    initial_balance: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    nav: float
    total_trades: int
    winning_trades: int
    win_rate: float
    total_opportunities: int
    open_positions: int
    last_trade_time: Optional[datetime] = None


@dataclass
class NavPoint:
    timestamp: str
    intra_arb: float
    logic_arb: float
    market_making: float
    weather: float = 100.0
    crypto_mm: float = 100.0
    near_certain: float = 100.0


@dataclass
class StrategyMetrics:
    strategy: StrategyName
    nav: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    pnl_pct: float
    total_trades: int
    winning_trades: int
    win_rate: float
    open_positions: int
    total_opportunities: int
    status: str
    last_scan: Optional[str]
    opportunities_per_hour: float


@dataclass
class BotState:
    running: bool
    paper_mode: bool
    uptime_seconds: float
    markets_tracked: int
    last_market_refresh: Optional[str]
    strategies: Dict[str, StrategyMetrics]
    nav_history: List[NavPoint]
    recent_trades: List[Dict[str, Any]]
    open_positions: List[Dict[str, Any]]
