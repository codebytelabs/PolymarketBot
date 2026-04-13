import { useState } from "react";
import clsx from "clsx";
import { StrategyKey, StrategyMetrics, PaperPosition, PaperTrade, STRATEGY_META } from "../types";
import PositionsTable from "./PositionsTable";
import TxTable from "./TxTable";

type Tab = "positions" | "trades";

interface Props {
  strategyKey: StrategyKey;
  metrics: StrategyMetrics;
  positions: PaperPosition[];
  trades: PaperTrade[];
  mmActiveQuotes?: number;
  mmLpDeployed?: number;
}

function StatBox({
  label,
  value,
  subtext,
  highlight,
}: {
  label: string;
  value: string;
  subtext?: string;
  highlight?: "green" | "blue" | "violet" | "neutral";
}) {
  const highlightClass = {
    green: "text-emerald-400",
    blue: "text-blue-400",
    violet: "text-violet-400",
    neutral: "text-gray-200",
  }[highlight ?? "neutral"];
  return (
    <div className="bg-gray-800/60 rounded-lg px-2.5 py-2 min-w-[72px]">
      <div className="text-xs text-gray-500 mb-0.5">{label}</div>
      <div className={clsx("text-sm font-mono font-semibold", highlightClass)}>{value}</div>
      {subtext && <div className="text-xs text-gray-600 mt-0.5">{subtext}</div>}
    </div>
  );
}

export default function StrategyPanel({
  strategyKey, metrics, positions, trades, mmActiveQuotes, mmLpDeployed,
}: Props) {
  const [tab, setTab] = useState<Tab>("positions");
  const meta = STRATEGY_META[strategyKey];
  const pnlPos = metrics.total_pnl >= 0;
  const navGrowth = metrics.nav - 100;
  const navGrowthPct = ((navGrowth / 100) * 100).toFixed(3);

  const statusDot =
    metrics.status === "scanning"
      ? "bg-yellow-400 animate-pulse"
      : metrics.status === "idle"
      ? "bg-emerald-400"
      : "bg-gray-500";

  const colorMap: Record<StrategyKey, string> = {
    market_making: "border-violet-500/40 glow-purple",
    near_certain: "border-fuchsia-500/40 glow-fuchsia",
    bs_strike: "border-emerald-500/40 glow-emerald",
    daily_updown: "border-amber-500/40 glow-amber",
    weather: "border-sky-500/40 glow-sky",
  };

  return (
    <div className={clsx("bg-gray-900 border rounded-xl overflow-hidden flex flex-col", colorMap[strategyKey])}>
      <div className="px-4 pt-3 pb-2.5 border-b border-gray-800">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className={clsx("w-2 h-2 rounded-full", statusDot)} />
              <h3 className="text-base font-bold text-white">{meta.label}</h3>
              <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full">
                PAPER
              </span>
            </div>
            <p className="text-xs text-gray-500">{meta.description}</p>
          </div>
          <div className="text-right">
            <div className="text-xl font-mono font-bold" style={{ color: meta.color }}>
              ${metrics.nav.toFixed(3)}
            </div>
            <div className={clsx("text-sm font-mono", pnlPos ? "text-emerald-400" : "text-red-400")}>
              {pnlPos ? "▲" : "▼"} {pnlPos ? "+" : ""}{navGrowthPct}%
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <StatBox label="NAV" value={`$${metrics.nav.toFixed(3)}`} highlight={pnlPos ? "green" : "neutral"} />
          <StatBox label="Cash" value={`$${metrics.cash.toFixed(3)}`} />
          <StatBox
            label="Real. PnL"
            value={`${metrics.realized_pnl >= 0 ? "+" : ""}$${metrics.realized_pnl.toFixed(4)}`}
            highlight={metrics.realized_pnl >= 0 ? "green" : "neutral"}
          />
          <StatBox
            label="Unreal. PnL"
            value={`${metrics.unrealized_pnl >= 0 ? "+" : ""}$${metrics.unrealized_pnl.toFixed(4)}`}
          />
          <StatBox label="Trades" value={String(metrics.total_trades)} subtext={`${metrics.win_rate}% win`} />
          <StatBox label="Open Pos" value={String(metrics.open_positions)} />
          <StatBox
            label="Ops/hr"
            value={String(metrics.opportunities_per_hour)}
            highlight="blue"
          />
          {strategyKey === "market_making" && (
            <>
              <StatBox label="Quotes" value={String(mmActiveQuotes ?? 0)} highlight="violet" />
              <StatBox label="LP $" value={`$${(mmLpDeployed ?? 0).toFixed(2)}`} highlight="violet" />
            </>
          )}
        </div>

        <div className="flex items-center gap-3 mt-2 text-xs text-gray-600">
          <span>Scans: {metrics.scan_count}</span>
          <span>•</span>
          <span>
            Last:{" "}
            {metrics.last_scan
              ? (() => { try { return new Date(metrics.last_scan).toLocaleTimeString(); } catch { return "—"; } })()
              : "—"}
          </span>
          <span>•</span>
          <span>Total ops: {metrics.total_opportunities}</span>
        </div>
      </div>

      <div className="px-4 pt-2.5 flex-1 flex flex-col min-h-0">
        <div className="flex gap-1 border-b border-gray-800 mb-2">
          {(["positions", "trades"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={clsx(
                "px-4 py-2 text-xs font-medium capitalize rounded-t border-b-2 transition-colors",
                tab === t
                  ? "border-current text-white"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              )}
              style={tab === t ? { borderColor: meta.color, color: meta.color } : {}}
            >
              {t === "positions" ? `Positions (${positions.filter(p => p.strategy === strategyKey && p.status === "open").length})` : `Trades (${trades.filter(t2 => t2.strategy === strategyKey).length})`}
            </button>
          ))}
        </div>
        <div className="overflow-y-auto max-h-[220px] pb-3">
          {tab === "positions" ? (
            <PositionsTable positions={positions} strategy={strategyKey} />
          ) : (
            <TxTable trades={trades} strategy={strategyKey} />
          )}
        </div>
      </div>
    </div>
  );
}
