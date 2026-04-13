import { useState, useEffect } from "react";
import { PaperPosition, STRATEGY_META, StrategyKey } from "../types";
import { format } from "date-fns";
import clsx from "clsx";

function computeRemaining(resolutionTime: string | null): string {
  if (!resolutionTime) return "—";
  try {
    const diff = new Date(resolutionTime).getTime() - Date.now();
    if (diff <= 0) return "expired";
    const h = Math.floor(diff / 3_600_000);
    const m = Math.floor((diff % 3_600_000) / 60_000);
    const s = Math.floor((diff % 60_000) / 1_000);
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  } catch { return "—"; }
}

function Countdown({ resolutionTime }: { resolutionTime: string | null }) {
  const [remaining, setRemaining] = useState(() => computeRemaining(resolutionTime));

  useEffect(() => {
    const id = setInterval(() => setRemaining(computeRemaining(resolutionTime)), 1_000);
    return () => clearInterval(id);
  }, [resolutionTime]);

  if (!resolutionTime || remaining === "—") return <span className="text-gray-600">—</span>;

  const diff = new Date(resolutionTime).getTime() - Date.now();
  const urgency =
    remaining === "expired" ? "text-red-500 font-semibold" :
    diff < 5 * 60_000  ? "text-red-400 animate-pulse font-semibold" :
    diff < 30 * 60_000 ? "text-amber-400 font-semibold" :
    "text-gray-400";

  return <span className={clsx("font-mono tabular-nums", urgency)}>{remaining}</span>;
}

interface Props {
  positions: PaperPosition[];
  strategy?: StrategyKey;
}

export default function PositionsTable({ positions, strategy }: Props) {
  const filtered = strategy
    ? positions.filter((p) => p.strategy === strategy && p.status === "open")
    : positions.filter((p) => p.status === "open");

  if (filtered.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-gray-600">
        <span className="text-3xl mb-2">🔍</span>
        <span className="text-sm">No open positions — scanning markets...</span>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 border-b border-gray-800">
            <th className="text-left py-2 pr-3 font-medium">Opened</th>
            {!strategy && <th className="text-left py-2 pr-3 font-medium">Strategy</th>}
            <th className="text-left py-2 pr-3 font-medium">Direction</th>
            <th className="text-left py-2 pr-3 font-medium max-w-xs">Market</th>
            <th className="text-right py-2 pr-3 font-medium">Cost</th>
            <th className="text-right py-2 pr-3 font-medium">Unr. PnL</th>
            <th className="text-right py-2 font-medium">Expires</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((p) => {
            const unrealized = p.current_value - p.cost_basis;
            const meta = STRATEGY_META[p.strategy];
            return (
              <tr key={p.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="py-1.5 pr-3 text-gray-500 whitespace-nowrap">
                  {(() => { try { return format(new Date(p.open_time), "HH:mm:ss"); } catch { return "—"; } })()}
                </td>
                {!strategy && (
                  <td className="py-1.5 pr-3">
                    <span className="font-medium" style={{ color: meta?.color }}>
                      {meta?.label}
                    </span>
                  </td>
                )}
                <td className="py-1.5 pr-3">
                  <span className="bg-gray-800 text-gray-300 px-1.5 py-0.5 rounded font-mono text-xs truncate max-w-[120px] block"
                    title={p.direction}>
                    {p.direction?.slice(0, 18)}{p.direction?.length > 18 ? "…" : ""}
                  </span>
                </td>
                <td className="py-1.5 pr-3 max-w-xs">
                  <span className="truncate block text-gray-300" title={p.market_question}>
                    {p.market_question?.slice(0, 55)}{p.market_question?.length > 55 ? "…" : ""}
                  </span>
                  {p.leg2_question && (
                    <span className="truncate block text-gray-500 mt-0.5" title={p.leg2_question}>
                      + {p.leg2_question.slice(0, 40)}…
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-300">
                  ${p.cost_basis.toFixed(3)}
                </td>
                <td className={clsx("py-1.5 pr-3 text-right font-mono font-semibold",
                  unrealized >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {unrealized >= 0 ? "+" : ""}${unrealized.toFixed(4)}
                </td>
                <td className="py-1.5 text-right whitespace-nowrap">
                  <Countdown resolutionTime={p.resolution_time} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
