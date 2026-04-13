# PolyBot — Polymarket Paper Trading Engine

> Automated prediction-market trading bot with a real-time React dashboard.  
> Runs in **paper mode** (simulated fills) — no real money at risk.

---

## Overview

PolyBot scans Polymarket's CLOB order books for quantifiable edges across three active strategies, executes paper trades, tracks P&L per strategy, and streams live data to a web dashboard.

```
┌─────────────────────────────────────────────┐
│  Browser  →  React Dashboard (port 80)      │
│               ↕  WebSocket                  │
│  FastAPI Backend (port 8000)                │
│    ├── Market Data Loop (Gamma API)          │
│    ├── Strategy: Daily Up/Down              │
│    ├── Strategy: Weather Arb                │
│    ├── Strategy: Near Certainty             │
│    └── SQLite DB  (/data/polybot.db)        │
└─────────────────────────────────────────────┘
```

---

## Active Strategies

| Strategy | Edge Source | Scan Interval | Max Positions |
|---|---|---|---|
| **Daily Up/Down** | GBM fair-value vs 5-min crypto direction markets | 10s | 15 |
| **Weather Arb** | Open-Meteo forecast vs Polymarket temperature markets | 60s | 8 |
| **Near Certainty** | High-conviction YES markets (82–96¢) expiring within 48h | 5s | 10 |

> **Market Making** and **BS Strike Arb** are implemented but currently disabled (zero fills / zero candidates in live markets).

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, aiohttp, aiosqlite |
| Frontend | React 18, TypeScript, Recharts, TailwindCSS |
| DB | SQLite (persisted Docker volume) |
| Infra | Docker Compose, nginx |
| Market Data | Polymarket Gamma API, Binance REST, Open-Meteo |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- SSH access to a VPS (or run locally)

### Local development

```bash
# 1. Clone
git clone <repo-url> && cd PolymarketBot

# 2. Configure environment
cp .env.example .env
# Edit .env — set PAPER_MODE=true (default)

# 3. Build and run
docker compose up --build

# 4. Open dashboard
open http://localhost
```

Backend API is available at `http://localhost:8000`.

### Deploy to VPS

```bash
# Uses deploy.sh — rsync source then rebuild
./deploy.sh
```

See `cloudVMs.md` for VM provisioning notes.

---

## Environment Variables

All variables have defaults. Override via `.env` or Docker Compose environment block.

| Variable | Default | Description |
|---|---|---|
| `PAPER_MODE` | `true` | Simulate trades (no real execution) |
| `DB_PATH` | `/data/polybot.db` | SQLite database path |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `MARKET_REFRESH_INTERVAL` | `30` | Seconds between Gamma API market refreshes |
| `WEATHER_MIN_EDGE` | `0.12` | Min forecast vs market price gap to enter |
| `WEATHER_MAX_POSITIONS` | `8` | Max concurrent weather positions |
| `WEATHER_KELLY_FRACTION` | `0.25` | Quarter-Kelly position sizing |
| `NC_MIN_YES_PRICE` | `0.82` | Min YES ask price to enter near-certainty trade |
| `NC_MAX_YES_PRICE` | `0.96` | Max YES ask price (above = too little upside) |
| `NC_CLOSE_THRESHOLD` | `0.97` | Close when YES bid crosses this level |
| `UD_MIN_EDGE` | `0.04` | Min GBM fair-value vs market gap to enter |
| `UD_MAX_POSITIONS` | `15` | Max concurrent direction positions |
| `UD_POSITION_SIZE` | `5.0` | USD per Up/Down position |
| `PRIVATE_KEY` | — | Only needed for live (non-paper) trading |

Full list of all tunable params: [`backend/app/config.py`](backend/app/config.py)

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | Bot status, uptime, strategy states |
| `GET` | `/api/trades?strategy=X&limit=N` | Recent closed trades |
| `GET` | `/api/positions?strategy=X` | Open positions |
| `GET` | `/api/nav?limit=N` | NAV history |
| `GET` | `/api/health` | Health check |
| `WS` | `/ws` | Live state stream (strategies, trades, positions, NAV) |

---

## Project Structure

```
PolymarketBot/
├── backend/
│   ├── main.py                  # FastAPI app, strategy orchestration
│   ├── requirements.txt
│   ├── Dockerfile
│   └── app/
│       ├── config.py            # All tunable parameters
│       ├── database.py          # SQLite schema + queries
│       ├── market_data.py       # Gamma API market data loop
│       ├── models.py            # Pydantic models, enums
│       ├── paper_trader.py      # PaperWallet — simulated execution
│       ├── strategy_daily_updown.py
│       ├── strategy_weather.py
│       ├── strategy_near_certainty.py
│       ├── strategy_market_making.py  # disabled
│       └── strategy_bs_strike.py      # disabled
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Main layout, strategy panels
│   │   ├── components/
│   │   │   ├── NavChart.tsx     # Portfolio NAV chart (zoomable)
│   │   │   └── StrategyPanel.tsx
│   │   ├── hooks/useWebSocket.ts
│   │   └── types.ts
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── deploy.sh
└── README.md
```

---

## Dashboard

| Section | Shows |
|---|---|
| **Portfolio NAV chart** | Live NAV per strategy over time, zoomable |
| **Strategy panels** | Per-strategy: NAV, cash, PnL, open positions, trade log |
| **All Strategies · Recent Activity** | Combined NAV summary + last 30 trades |

---

## Paper Trading Notes

- Every strategy starts with **$100 virtual cash**.
- Position sizing uses Kelly criterion or fixed percentage of NAV.
- Closed positions query the **Gamma API** for actual YES/NO resolution — no fabricated wins.
- Unrealized PnL uses live order book bid prices.
- NAV history is persisted in SQLite and survives restarts.

---

## Related Docs

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — component design and data flow
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to add strategies or contribute
- [`POLYMARKET_STRATEGIES.md`](POLYMARKET_STRATEGIES.md) — strategy research report
- [`cloudVMs.md`](cloudVMs.md) — VPS setup notes

---

*Paper mode only · Not financial advice*
