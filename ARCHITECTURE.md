# Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  EXTERNAL APIS                                                   │
│  Gamma API (polymarket.com)   Binance REST   Open-Meteo         │
└────────────┬──────────────────────┬──────────────┬──────────────┘
             │                      │              │
             ▼                      ▼              ▼
┌──────────────────────────────────────────────────────────────────┐
│  BACKEND  (FastAPI + asyncio, port 8000)                        │
│                                                                  │
│  market_data.py                                                  │
│    └── market_data_loop()  ←── Gamma API  (every 30s)           │
│         Parses markets, order books → in-memory dict            │
│                                                                  │
│  Strategy Tasks  (each runs in own asyncio task)                │
│    ├── strategy_daily_updown.py   scan every 10s               │
│    │     Binance price + GBM → fair P(up) → CLOB edge          │
│    ├── strategy_weather.py        scan every 60s               │
│    │     Open-Meteo forecast → temperature market edge         │
│    └── strategy_near_certainty.py scan every 5s               │
│          82–96¢ YES markets expiring within 48h                │
│                                                                  │
│  paper_trader.py  (PaperWallet)                                 │
│    open_position() / close_position() → DB + in-memory state   │
│                                                                  │
│  database.py  (aiosqlite)                                       │
│    tables: trades, positions, wallet_state, nav_history         │
│                                                                  │
│  main.py  (FastAPI)                                             │
│    REST: /api/status  /api/trades  /api/positions  /api/nav     │
│    WS:   /ws  → broadcast state every 2s                       │
└────────────────────────────┬─────────────────────────────────────┘
                             │ WebSocket
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  FRONTEND  (React + Vite, served via nginx port 80)             │
│                                                                  │
│  useWebSocket.ts  → connects to /ws, holds full AppState        │
│  App.tsx          → layout, strategy panel grid, trades table   │
│  NavChart.tsx     → Recharts line chart, drag/scroll zoom       │
│  StrategyPanel.tsx→ per-strategy metrics, positions, trades     │
└──────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Market Scan → Trade

```
1. market_data_loop fetches 200 active markets from Gamma API
2. Strategy scan_once() reads in-memory market dict
3. Computes fair probability using model (GBM / weather forecast / price level)
4. Compares to market ask price → edge = |fair - ask|
5. If edge > threshold AND position slots available:
   wallet.open_position() → inserts row into positions + wallet_state tables
6. On next scan, _close_positions() checks:
   a. Market still in active dict? → check near-expiry, price target hit
   b. Market gone from dict? → _fetch_resolution() queries Gamma API
      → close at 0.99 (WIN) or 0.01 (LOSS) based on actual resolution
7. close_position() → inserts row into trades, updates wallet_state
```

### WebSocket Broadcast

```
ws_broadcast_loop (every 2s):
  _build_full_state()
    → PaperWallet.get_state() for each strategy
    → md.get_markets() count
    → recent_trades / open_positions lists
  → save_nav_point() to DB
  → broadcast to all connected WS clients
```

---

## Key Modules

### `paper_trader.py` — PaperWallet

Central simulated execution engine. Persists all state to SQLite.

```
PaperWallet
  .cash                 float
  .open_positions       List[Position]
  .nav                  cash + unrealized_pnl
  .open_position(...)   → Position
  .close_position(...)  → Trade
  .restore()            → loads from DB on startup
  .get_state()          → WalletState snapshot
```

### `market_data.py` — Market Cache

```
market_data_loop(interval)  → runs forever, refreshes every N seconds
get_markets() → Dict[market_id, MarketSnapshot]

MarketSnapshot fields:
  id, question, end_date, volume
  yes_best_bid, yes_best_ask, no_best_bid, no_best_ask
```

### `database.py` — Schema

```sql
trades (
  id TEXT PRIMARY KEY,
  strategy TEXT, market_id TEXT, market_question TEXT,
  trade_type TEXT, direction TEXT, price REAL, size REAL,
  cost REAL, pnl_at_close REAL, close_reason TEXT,
  timestamp DATETIME
)

positions (
  id TEXT PRIMARY KEY,
  strategy TEXT, market_id TEXT, market_question TEXT,
  direction TEXT, size REAL, cost_basis REAL,
  price REAL, resolution_time DATETIME,
  opened_at DATETIME, notes TEXT
)

wallet_state (
  strategy TEXT PRIMARY KEY,
  cash REAL, realized_pnl REAL, unrealized_pnl REAL,
  total_trades INT, winning_trades INT,
  total_opportunities INT
)

nav_history (
  ts DATETIME, market_making REAL, near_certain REAL,
  bs_strike REAL, daily_updown REAL, weather REAL
)
```

---

## Strategy Design Pattern

Every strategy follows the same interface:

```python
async def run(wallet: PaperWallet):
    """Entry point — called once at startup, loops forever."""

async def scan_once(wallet: PaperWallet):
    """One full scan: close stale positions + open new ones."""

def get_status() -> dict:
    """Returns {last_scan, scan_count, running} for the API."""

def stop():
    """Signals the run() loop to exit cleanly."""
```

Close logic **always** queries the Gamma API for actual market resolution (`_fetch_resolution`) — no assumed wins.

---

## Disabled Strategies

| Strategy | File | Reason Disabled |
|---|---|---|
| Market Making | `strategy_market_making.py` | Paper trading has no counterparty to fill quotes |
| BS Strike Arb | `strategy_bs_strike.py` | Zero candidates in current 200-market scan set |

Both wallets remain initialized so the DB schema and state are preserved. Re-enable by uncommenting the `asyncio.create_task(...)` lines in `main.py`.

---

## Deployment

```
VPS (Google Cloud / any Linux VPS)
  └── /opt/polybot/
       ├── docker-compose.yml
       ├── backend/           ← Python source
       └── frontend/          ← React source

Containers:
  polybot-backend   → builds from backend/Dockerfile
  polybot-frontend  → builds from frontend/Dockerfile (nginx)

Volume:
  polybot_data:/data  → SQLite DB, survives rebuilds

Ports:
  :80    nginx serving frontend + proxying /ws
  :8000  FastAPI (internal, exposed for debugging)
```
