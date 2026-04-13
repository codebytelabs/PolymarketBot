import { useMemo } from "react";
import { useWebSocket, WsStatus } from "./hooks/useWebSocket";
import NavChart from "./components/NavChart";
import StrategyPanel from "./components/StrategyPanel";
import { StrategyKey, STRATEGY_META } from "./types";

function StatusBadge({ status }: { status: WsStatus }) {
  const cfg = {
    connected: { dot: "bg-emerald-400 animate-pulse", text: "text-emerald-400", label: "LIVE" },
    connecting: { dot: "bg-yellow-400 animate-pulse", text: "text-yellow-400", label: "CONNECTING" },
    disconnected: { dot: "bg-red-400", text: "text-red-400", label: "DISCONNECTED" },
    error: { dot: "bg-red-500", text: "text-red-500", label: "ERROR" },
  }[status];
  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
      <span className={`text-xs font-mono font-semibold ${cfg.text}`}>{cfg.label}</span>
    </div>
  );
}

function formatUptime(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export default function App() {
  const { state, wsStatus } = useWebSocket();

  const ACTIVE: StrategyKey[] = ["near_certain", "daily_updown", "weather"];
  const TOP_ROW: StrategyKey[] = ["daily_updown", "weather"];
  const BASE_NAV = ACTIVE.length * 100;

  const totalNav = useMemo(() => {
    if (!state?.strategies) return BASE_NAV;
    return ACTIVE.reduce((s, k) => s + (state.strategies[k]?.nav ?? 100), 0);
  }, [state]);

  const totalPnl = totalNav - BASE_NAV;
  const totalPnlPct = ((totalPnl / BASE_NAV) * 100).toFixed(3);

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-gray-800 bg-gray-950/95 backdrop-blur sticky top-0 z-50">
        <div className="max-w-screen-2xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-2xl">🤖</div>
            <div>
              <h1 className="text-lg font-bold text-white leading-tight">PolyBot</h1>
              <p className="text-xs text-gray-500">Paper Trading Dashboard · 3 Active Strategies</p>
            </div>
            <span className="ml-2 px-2.5 py-0.5 rounded-full bg-yellow-500/15 text-yellow-400 text-xs font-semibold border border-yellow-500/30">
              PAPER MODE
            </span>
          </div>

          <div className="flex items-center gap-6">
            {state?.ready && (
              <>
                <div className="text-center hidden sm:block">
                  <div className="text-xs text-gray-500">Combined NAV</div>
                  <div className={`text-base font-mono font-bold ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    ${totalNav.toFixed(2)}
                  </div>
                  <div className={`text-xs ${totalPnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                    {totalPnl >= 0 ? "+" : ""}{totalPnlPct}% from ${BASE_NAV}
                  </div>
                </div>
                <div className="text-center hidden sm:block">
                  <div className="text-xs text-gray-500">Markets</div>
                  <div className="text-sm font-mono font-semibold text-white">{state.markets_tracked}</div>
                </div>
                <div className="text-center hidden sm:block">
                  <div className="text-xs text-gray-500">Uptime</div>
                  <div className="text-sm font-mono font-semibold text-white">{formatUptime(state.uptime_seconds)}</div>
                </div>
              </>
            )}
            <StatusBadge status={wsStatus} />
          </div>
        </div>
      </header>

      <main className="max-w-screen-2xl mx-auto px-6 py-4 space-y-4">
        {!state?.ready ? (
          <div className="flex flex-col items-center justify-center h-80 text-gray-600 gap-4">
            <div className="text-5xl animate-spin">⚙️</div>
            <div className="text-center">
              <p className="text-lg font-medium text-gray-400">
                {wsStatus === "connecting" ? "Connecting to PolyBot..." : "Waiting for bot data..."}
              </p>
              <p className="text-sm text-gray-600 mt-1">
                Bot is fetching markets and warming up strategies
              </p>
            </div>
          </div>
        ) : (
          <>
            <NavChart data={state.nav_history} />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
              {(["daily_updown", "weather", "near_certain"] as StrategyKey[]).map((key) => (
                <StrategyPanel
                  key={key}
                  strategyKey={key}
                  metrics={state.strategies[key]}
                  positions={state.open_positions}
                  trades={state.recent_trades}
                />
              ))}
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <h2 className="text-base font-semibold text-white mb-4">All Strategies · Recent Activity</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
                {ACTIVE.map((key) => {
                  const m = state.strategies[key];
                  const meta = STRATEGY_META[key];
                  const pnl = m.nav - 100;
                  return (
                    <div key={key} className="bg-gray-800/50 rounded-lg p-4 flex items-center justify-between">
                      <div>
                        <div className="text-xs font-medium mb-1" style={{ color: meta.color }}>
                          {meta.label}
                        </div>
                        <div className="text-lg font-mono font-bold text-white">${m.nav.toFixed(3)}</div>
                        <div className="text-xs text-gray-500">{m.total_trades} trades · {m.win_rate}% win</div>
                      </div>
                      <div className={`text-right text-sm font-mono font-semibold ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {pnl >= 0 ? "+" : ""}${pnl.toFixed(3)}
                        <div className="text-xs">
                          {pnl >= 0 ? "+" : ""}{((pnl / 100) * 100).toFixed(2)}%
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {state.recent_trades.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-500 border-b border-gray-800">
                        <th className="text-left py-2 pr-3 font-medium">Time</th>
                        <th className="text-left py-2 pr-3 font-medium">Strategy</th>
                        <th className="text-left py-2 pr-3 font-medium">Type</th>
                        <th className="text-left py-2 pr-3 font-medium">Market</th>
                        <th className="text-right py-2 pr-3 font-medium">Cost</th>
                        <th className="text-right py-2 font-medium">PnL</th>
                      </tr>
                    </thead>
                    <tbody>
                      {state.recent_trades.filter(t => ACTIVE.includes(t.strategy as StrategyKey)).slice(0, 30).map((t) => {
                        const meta = STRATEGY_META[t.strategy];
                        return (
                          <tr key={t.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                            <td className="py-1.5 pr-3 text-gray-500 whitespace-nowrap">
                              {(() => { try { return new Date(t.timestamp).toLocaleTimeString(); } catch { return "—"; } })()}
                            </td>
                            <td className="py-1.5 pr-3">
                              <span className="font-medium text-xs" style={{ color: meta?.color }}>{meta?.label}</span>
                            </td>
                            <td className="py-1.5 pr-3 font-mono text-gray-400">{t.trade_type}</td>
                            <td className="py-1.5 pr-3 text-gray-300 max-w-xs">
                              <span className="truncate block" title={t.market_question}>
                                {t.market_question?.slice(0, 55)}{t.market_question?.length > 55 ? "…" : ""}
                              </span>
                            </td>
                            <td className="py-1.5 pr-3 text-right font-mono text-gray-300">
                              ${Math.abs(t.cost).toFixed(3)}
                            </td>
                            <td className="py-1.5 text-right font-mono font-semibold">
                              {t.pnl_at_close != null ? (
                                <span className={t.pnl_at_close >= 0 ? "text-emerald-400" : "text-red-400"}>
                                  {t.pnl_at_close >= 0 ? "+" : ""}${t.pnl_at_close.toFixed(4)}
                                </span>
                              ) : (
                                <span className="text-gray-600">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </main>

      <footer className="border-t border-gray-800 mt-8 py-4 text-center text-xs text-gray-700">
        PolyBot Paper Trading Engine · Near Certain | Daily Up/Down | Weather Arb
        · Not financial advice · Paper mode only
      </footer>
    </div>
  );
}
