import os
from dotenv import load_dotenv

load_dotenv()

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

PAPER_WALLET_INITIAL = 100.0
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS", "")
CHAIN_ID = 137

INTRA_ARB_SCAN_INTERVAL = float(os.getenv("INTRA_ARB_SCAN_INTERVAL", "5"))
LOGIC_ARB_SCAN_INTERVAL = float(os.getenv("LOGIC_ARB_SCAN_INTERVAL", "5"))
MM_SCAN_INTERVAL = float(os.getenv("MM_SCAN_INTERVAL", "1"))
MARKET_REFRESH_INTERVAL = float(os.getenv("MARKET_REFRESH_INTERVAL", "15"))
WS_BROADCAST_INTERVAL = float(os.getenv("WS_BROADCAST_INTERVAL", "1"))

INTRA_ARB_MIN_EDGE = float(os.getenv("INTRA_ARB_MIN_EDGE", "0.003"))
INTRA_ARB_FEE_ESTIMATE = float(os.getenv("INTRA_ARB_FEE_ESTIMATE", "0.002"))
INTRA_ARB_MAX_POSITION_PCT = 0.05
INTRA_ARB_MAX_TRADE_USD = float(os.getenv("INTRA_ARB_MAX_TRADE_USD", "100.0"))

LOGIC_ARB_MIN_EDGE = float(os.getenv("LOGIC_ARB_MIN_EDGE", "0.05"))
# Tiered position sizing: aggressive when small, conservative when large
# Override any tier via .env: LOGIC_ARB_TIER1_PCT, LOGIC_ARB_TIER2_PCT, LOGIC_ARB_TIER3_PCT
LOGIC_ARB_TIER1_PCT   = float(os.getenv("LOGIC_ARB_TIER1_PCT",   "0.20"))  # NAV <= tier2 threshold
LOGIC_ARB_TIER2_PCT   = float(os.getenv("LOGIC_ARB_TIER2_PCT",   "0.10"))  # NAV <= tier3 threshold
LOGIC_ARB_TIER3_PCT   = float(os.getenv("LOGIC_ARB_TIER3_PCT",   "0.05"))  # NAV > tier3 threshold
LOGIC_ARB_TIER2_NAV   = float(os.getenv("LOGIC_ARB_TIER2_NAV",   "500"))   # $500 breakpoint
LOGIC_ARB_TIER3_NAV   = float(os.getenv("LOGIC_ARB_TIER3_NAV",   "1000"))  # $1000 breakpoint
LOGIC_ARB_MAX_TRADE_USD = float(os.getenv("LOGIC_ARB_MAX_TRADE_USD", "50000.0"))  # effectively uncapped

LOGIC_ARB_MAX_GROUP_SIZE = int(os.getenv("LOGIC_ARB_MAX_GROUP_SIZE", "6"))  # skip non-exclusive groups

MM_MIN_SPREAD = float(os.getenv("MM_MIN_SPREAD", "0.03"))
MM_QUOTE_HALF_SPREAD = 0.015
MM_MAX_POSITION_PCT = 0.20
# Hard cap per quote regardless of NAV — prevents runaway compounding as wallet grows
MM_MAX_QUOTE_CAPITAL_USD = float(os.getenv("MM_MAX_QUOTE_CAPITAL_USD", "25.0"))
MM_LP_REWARD_RATE_PER_HOUR = float(os.getenv("MM_LP_REWARD_RATE_PER_HOUR", "0.00003"))

# Crypto 15-min Maker MM: target BTC/ETH/SOL short-expiry markets, buy both sides at <$1
CRYPTO_MM_SCAN_INTERVAL = float(os.getenv("CRYPTO_MM_SCAN_INTERVAL", "3"))
CRYPTO_MM_MIN_EDGE = float(os.getenv("CRYPTO_MM_MIN_EDGE", "0.005"))   # combined ask must be < 0.995
CRYPTO_MM_POSITION_PCT = float(os.getenv("CRYPTO_MM_POSITION_PCT", "0.30"))
CRYPTO_MM_MAX_CAPITAL_USD = float(os.getenv("CRYPTO_MM_MAX_CAPITAL_USD", "30.0"))
CRYPTO_MM_MAX_EXPIRY_HOURS = float(os.getenv("CRYPTO_MM_MAX_EXPIRY_HOURS", "4.0"))

# Weather strategy: uses Open-Meteo free API to find forecast vs market price edges
WEATHER_SCAN_INTERVAL = float(os.getenv("WEATHER_SCAN_INTERVAL", "60"))
WEATHER_MIN_EDGE = float(os.getenv("WEATHER_MIN_EDGE", "0.12"))         # forecast prob vs market price must differ by 12%+
WEATHER_POSITION_PCT = float(os.getenv("WEATHER_POSITION_PCT", "0.20"))
WEATHER_MAX_CAPITAL_USD = float(os.getenv("WEATHER_MAX_CAPITAL_USD", "20.0"))
WEATHER_KELLY_FRACTION = float(os.getenv("WEATHER_KELLY_FRACTION", "0.25"))  # quarter-Kelly conservative sizing
WEATHER_MAX_POSITIONS = int(os.getenv("WEATHER_MAX_POSITIONS", "8"))         # max concurrent open positions

# Near-Certainty Conviction Bot: buy high-probability YES markets (82-96¢) expecting $1 resolution
NC_SCAN_INTERVAL = float(os.getenv("NC_SCAN_INTERVAL", "5"))
NC_MIN_YES_PRICE = float(os.getenv("NC_MIN_YES_PRICE", "0.82"))    # min YES ask to enter
NC_MAX_YES_PRICE = float(os.getenv("NC_MAX_YES_PRICE", "0.96"))    # max YES ask (above = too little upside)
NC_CLOSE_THRESHOLD = float(os.getenv("NC_CLOSE_THRESHOLD", "0.97"))  # close when YES bid hits this
NC_MAX_POSITIONS = int(os.getenv("NC_MAX_POSITIONS", "10"))          # max concurrent open positions
NC_POSITION_PCT = float(os.getenv("NC_POSITION_PCT", "0.05"))        # 5% NAV per position
NC_MAX_CAPITAL_USD = float(os.getenv("NC_MAX_CAPITAL_USD", "6.0"))   # hard cap per position
NC_MIN_VOLUME = float(os.getenv("NC_MIN_VOLUME", "500"))             # min market volume for quality

# Black-Scholes Daily Strike Arb: targets "BTC/ETH above $X on [date]" markets
BS_SCAN_INTERVAL   = float(os.getenv("BS_SCAN_INTERVAL",   "15"))    # seconds between scans
BS_MIN_EDGE        = float(os.getenv("BS_MIN_EDGE",        "0.06"))   # min |BS_prob - market_price|
BS_MAX_POSITIONS   = int(os.getenv("BS_MAX_POSITIONS",    "12"))     # max concurrent positions
BS_POSITION_SIZE   = float(os.getenv("BS_POSITION_SIZE",  "7.0"))    # dollars per position
BS_MIN_VOLUME      = float(os.getenv("BS_MIN_VOLUME",     "5"))      # low threshold — many new markets start small
BS_MIN_TIME_SEC    = float(os.getenv("BS_MIN_TIME_SEC",   "600"))    # min time-to-expiry in seconds (10 min)
BS_MAX_TIME_SEC    = float(os.getenv("BS_MAX_TIME_SEC",   "86400"))  # max time-to-expiry (24h)
BS_BTC_SIGMA       = float(os.getenv("BS_BTC_SIGMA",      "0.80"))   # BTC annualized volatility
BS_ETH_SIGMA       = float(os.getenv("BS_ETH_SIGMA",      "1.00"))   # ETH annualized volatility

# Daily Up/Down Direction: "Will BTC close up/down today?" markets
UD_SCAN_INTERVAL   = float(os.getenv("UD_SCAN_INTERVAL",  "10"))    # fast scan for 5-min markets
UD_MIN_EDGE        = float(os.getenv("UD_MIN_EDGE",        "0.04"))  # 4% edge threshold
UD_MAX_POSITIONS   = int(os.getenv("UD_MAX_POSITIONS",    "15"))    # many concurrent 5-min bets
UD_POSITION_SIZE   = float(os.getenv("UD_POSITION_SIZE",  "5.0"))
UD_MIN_VOLUME      = float(os.getenv("UD_MIN_VOLUME",     "1"))     # 5-min markets are new/low volume
UD_BTC_SIGMA       = float(os.getenv("UD_BTC_SIGMA",      "0.80"))
UD_ETH_SIGMA       = float(os.getenv("UD_ETH_SIGMA",      "1.00"))

MAX_MARKETS_TO_SCAN = int(os.getenv("MAX_MARKETS_TO_SCAN", "500"))
MIN_MARKET_VOLUME = float(os.getenv("MIN_MARKET_VOLUME", "0"))

DB_PATH = os.getenv("DB_PATH", "/data/polybot.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
