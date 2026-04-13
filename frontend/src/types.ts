export type StrategyKey = "market_making" | "near_certain" | "bs_strike" | "daily_updown" | "weather";

export interface StrategyMetrics {
  strategy: StrategyKey;
  nav: number;
  cash: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  pnl_pct: number;
  total_trades: number;
  winning_trades: number;
  win_rate: number;
  open_positions: number;
  total_opportunities: number;
  status: string;
  last_scan: string | null;
  opportunities_per_hour: number;
  scan_count: number;
}

export interface NavPoint {
  timestamp: string;
  market_making: number;
  near_certain: number;
  bs_strike: number;
  daily_updown: number;
  weather: number;
}

export interface PaperPosition {
  id: string;
  strategy: StrategyKey;
  market_id: string;
  market_question: string;
  direction: string;
  cost_basis: number;
  size: number;
  open_time: string;
  close_time: string | null;
  status: "open" | "closed" | "expired";
  realized_pnl: number | null;
  current_value: number;
  resolution_time: string | null;
  notes: string;
  leg2_market_id: string | null;
  leg2_question: string | null;
}

export interface PaperTrade {
  id: string;
  strategy: StrategyKey;
  market_id: string;
  market_question: string;
  trade_type: string;
  price: number;
  size: number;
  cost: number;
  timestamp: string;
  position_id: string;
  notes: string;
  pnl_at_close: number | null;
}

export interface BotState {
  type: string;
  ready: boolean;
  timestamp: string;
  uptime_seconds: number;
  paper_mode: boolean;
  markets_tracked: number;
  strategies: Record<StrategyKey, StrategyMetrics>;
  nav_history: NavPoint[];
  open_positions: PaperPosition[];
  recent_trades: PaperTrade[];
  mm_active_quotes: number;
  mm_lp_deployed: number;
}

export const STRATEGY_META: Record<
  StrategyKey,
  { label: string; color: string; tailwindColor: string; description: string }
> = {
  market_making: {
    label: "Market Making",
    color: "#a78bfa",
    tailwindColor: "violet",
    description: "Spread capture + LP reward farming",
  },
  near_certain: {
    label: "Near Certain",
    color: "#e879f9",
    tailwindColor: "fuchsia",
    description: "High-conviction YES accumulator (92-98¢ band, 7d window)",
  },
  bs_strike: {
    label: "BS Strike Arb",
    color: "#34d399",
    tailwindColor: "emerald",
    description: "Black-Scholes daily crypto strike mispricing (BTC/ETH above $X)",
  },
  daily_updown: {
    label: "Convergence",
    color: "#fbbf24",
    tailwindColor: "amber",
    description: "Buy near-certain outcomes (0.90-0.99) + pure arb across all markets",
  },
  weather: {
    label: "Weather Arb",
    color: "#38bdf8",
    tailwindColor: "sky",
    description: "Open-Meteo forecast vs market temperature threshold bets",
  },
};
