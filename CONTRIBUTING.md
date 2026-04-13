# Contributing

## Code Style

- **Python**: `snake_case` functions/variables, `PascalCase` classes
- **TypeScript/React**: `camelCase` functions/variables, `PascalCase` components
- Sanitize all external API data before use (Gamma, Binance, Open-Meteo)
- No secrets in source — use `.env` / environment variables only
- DRY: rewrite existing logic rather than adding parallel copies

---

## Adding a New Strategy

### 1. Create the strategy file

```
backend/app/strategy_<name>.py
```

Implement the standard interface:

```python
from app.paper_trader import PaperWallet

_running = False

async def run(wallet: PaperWallet):
    global _running
    _running = True
    while _running:
        await scan_once(wallet)
        await asyncio.sleep(SCAN_INTERVAL)

async def scan_once(wallet: PaperWallet):
    # 1. Close stale positions
    await _try_close_positions(wallet)
    # 2. Scan for new entries
    ...

def get_status() -> dict:
    return {"running": _running, "last_scan": ..., "scan_count": ...}

def stop():
    global _running
    _running = False
```

### 2. Add config parameters

In `backend/app/config.py`:

```python
MY_SCAN_INTERVAL  = float(os.getenv("MY_SCAN_INTERVAL", "10"))
MY_MIN_EDGE       = float(os.getenv("MY_MIN_EDGE",       "0.05"))
MY_MAX_POSITIONS  = int(os.getenv("MY_MAX_POSITIONS",    "10"))
MY_POSITION_SIZE  = float(os.getenv("MY_POSITION_SIZE",  "5.0"))
```

### 3. Wire into main.py

```python
from app.strategy_<name> import run as run_<name>, get_status as gs_<name>

# In startup, alongside the other wallets:
wallet_<name> = PaperWallet("<name>")
await wallet_<name>.restore()

# In the task creation block:
asyncio.create_task(run_<name>(wallet_<name>))

# In _build_full_state():
strategies["<name>"] = wallet_<name>.get_state()
```

### 4. Add to frontend

In `frontend/src/types.ts`, add `"<name>"` to the `StrategyKey` union and add its metadata to `STRATEGY_META`.

In `frontend/src/App.tsx`, add `"<name>"` to the `ACTIVE` and `TOP_ROW` (or bottom) arrays.

---

## Close Logic Rule

**Always** resolve positions against the actual Gamma API result. Never assume a win.

```python
async def _fetch_resolution(market_id: str) -> Optional[str]:
    # query GET https://gamma-api.polymarket.com/markets/{market_id}
    # return "YES", "NO", or None
```

---

## Testing

### Run locally (without Docker)

```bash
cd backend
pip install -r requirements.txt
DB_PATH=./local.db uvicorn main:app --reload --port 8000
```

### Check strategy logic in isolation

Each strategy exports `scan_once()` — call it with a mock wallet in a test file under `__tests__/`.

```python
# __tests__/test_daily_updown.py
import asyncio
from app.paper_trader import PaperWallet
from app.strategy_daily_updown import scan_once

async def test_scan():
    w = PaperWallet("daily_updown_test")
    await w.restore()
    await scan_once(w)
    # assert no exceptions, wallet state valid

asyncio.run(test_scan())
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # hot-reload dev server on :5173
npm run build    # TypeScript check + Vite bundle
```

---

## Deployment

```bash
# From project root — rsyncs source and rebuilds on VPS
./deploy.sh
```

To rebuild only the frontend or backend:

```bash
ssh root@<VM_IP> "cd /opt/polybot && docker compose up -d --build frontend"
ssh root@<VM_IP> "cd /opt/polybot && docker compose up -d --build backend"
```

---

## Resetting a Strategy Wallet

```bash
# SSH into VM
sqlite3 /var/lib/docker/volumes/polybot_data/_data/polybot.db

DELETE FROM trades    WHERE strategy = '<name>';
DELETE FROM positions WHERE strategy = '<name>';
DELETE FROM wallet_state WHERE strategy = '<name>';
UPDATE nav_history SET <name> = 100.0;
.quit
```

Then restart the backend container to reinitialise the wallet from scratch.
