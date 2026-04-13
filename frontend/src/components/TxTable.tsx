import { PaperTrade, STRATEGY_META, StrategyKey } from "../types";
import { format } from "date-fns";
import clsx from "clsx";

const TRADE_TYPE_BADGE: Record<string, string> = {
  BUY_BOTH: "bg-emerald-900 text-emerald-300",
  HEDGE: "bg-blue-900 text-blue-300",
  MM_BID: "bg-violet-900 text-violet-300",
  MM_ASK: "bg-purple-900 text-purple-300",
  LP_REWARD: "bg-yellow-900 text-yellow-300",
  CLOSE: "bg-gray-800 text-gray-400",
  BUY_YES: "bg-emerald-900 text-emerald-300",
  BUY_NO: "bg-orange-900 text-orange-300",
};

interface Props {
  trades: PaperTrade[];
  strategy?: StrategyKey;
  maxRows?: number;
}

export default function TxTable({ trades, strategy, maxRows = 20 }: Props) {
  const filtered = strategy ? trades.filter((t) => t.strategy === strategy) : trades;
  const visible = filtered.slice(0, maxRows);

  if (visible.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-gray-600">
        <span className="text-3xl mb-2">📭</span>
        <span className="text-sm">No trades yet — bot is scanning...</span>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 border-b border-gray-800">
            <th className="text-left py-2 pr-3 font-medium">Time</th>
            {!strategy && <th className="text-left py-2 pr-3 font-medium">Strategy</th>}
            <th className="text-left py-2 pr-3 font-medium">Type</th>
            <th className="text-left py-2 pr-3 font-medium max-w-xs">Market</th>
            <th className="text-right py-2 pr-3 font-medium">Price</th>
            <th className="text-right py-2 pr-3 font-medium">Size</th>
            <th className="text-right py-2 pr-3 font-medium">Cost</th>
            <th className="text-right py-2 font-medium">PnL</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((t) => {
            const pnl = t.pnl_at_close;
            const meta = STRATEGY_META[t.strategy];
            return (
              <tr key={t.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="py-1.5 pr-3 text-gray-500 whitespace-nowrap">
                  {(() => { try { return format(new Date(t.timestamp), "HH:mm:ss"); } catch { return t.timestamp; } })()}
                </td>
                {!strategy && (
                  <td className="py-1.5 pr-3">
                    <span className="font-medium" style={{ color: meta?.color }}>
                      {meta?.label}
                    </span>
                  </td>
                )}
                <td className="py-1.5 pr-3">
                  <span className={clsx("px-1.5 py-0.5 rounded text-xs font-mono", TRADE_TYPE_BADGE[t.trade_type] ?? "bg-gray-800 text-gray-400")}>
                    {t.trade_type}
                  </span>
                </td>
                <td className="py-1.5 pr-3 max-w-xs">
                  <span className="truncate block text-gray-300" title={t.market_question}>
                    {t.market_question?.slice(0, 60)}{t.market_question?.length > 60 ? "…" : ""}
                  </span>
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-300">
                  {t.price.toFixed(4)}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-300">
                  {t.size.toFixed(2)}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-300">
                  ${Math.abs(t.cost).toFixed(3)}
                </td>
                <td className="py-1.5 text-right font-mono font-semibold">
                  {pnl != null ? (
                    <span className={pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {pnl >= 0 ? "+" : ""}${pnl.toFixed(4)}
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
  );
}
