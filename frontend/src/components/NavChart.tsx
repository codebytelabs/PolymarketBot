import { useState, useRef, useCallback, useEffect } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
import { NavPoint, STRATEGY_META } from "../types";
import { format } from "date-fns";

interface Props {
  data: NavPoint[];
}

interface ZoomState {
  x1: number; // start index
  x2: number; // end index
  y1: number;
  y2: number;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-xl text-xs">
      <p className="text-gray-400 mb-2">
        {label ? format(new Date(label), "HH:mm:ss") : ""}
      </p>
      {payload.map((entry: any) => {
        const meta = STRATEGY_META[entry.dataKey as keyof typeof STRATEGY_META];
        const nav = entry.value as number;
        const pnl = nav - 100;
        const pnlPct = ((pnl / 100) * 100).toFixed(2);
        return (
          <div key={entry.dataKey} className="flex items-center gap-2 mb-1">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: entry.color }} />
            <span className="text-gray-300 w-20">{meta?.label}</span>
            <span className="font-mono font-semibold" style={{ color: entry.color }}>
              ${nav.toFixed(3)}
            </span>
            <span className={pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
              ({pnl >= 0 ? "+" : ""}{pnlPct}%)
            </span>
          </div>
        );
      })}
    </div>
  );
};

const ACTIVE_KEYS = ["near_certain", "daily_updown", "weather"] as const;

function computeYBounds(slice: NavPoint[], padFactor = 0.08) {
  const navs = slice.flatMap((d) => [
    d.near_certain ?? 100, d.daily_updown ?? 100, d.weather ?? 100,
  ]).filter(isFinite);
  if (!navs.length) return { yMin: 99, yMax: 101 };
  const lo = Math.min(...navs);
  const hi = Math.max(...navs);
  const pad = (hi - lo) * padFactor + 0.5;
  return { yMin: lo - pad, yMax: hi + pad };
}

export default function NavChart({ data }: Props) {
  const MAX_POINTS = 500;
  const sampledData =
    data.length > MAX_POINTS
      ? data.filter((_, i) => i % Math.ceil(data.length / MAX_POINTS) === 0)
      : data;

  const total = sampledData.length;

  // Zoom state: indices into sampledData
  const [zoom, setZoom] = useState<ZoomState | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selStart, setSelStart] = useState<number | null>(null);
  const [selEnd, setSelEnd] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isZoomed = zoom !== null;

  const visibleData = zoom
    ? sampledData.slice(zoom.x1, zoom.x2 + 1)
    : sampledData;

  const { yMin: autoYMin, yMax: autoYMax } = computeYBounds(visibleData);
  const yDomain: [number, number] = zoom
    ? [zoom.y1, zoom.y2]
    : [autoYMin, autoYMax];

  const reset = useCallback(() => {
    setZoom(null);
    setSelecting(false);
    setSelStart(null);
    setSelEnd(null);
  }, []);

  // Convert chart activeIndex to data index
  const getIdxFromActive = (active: any): number | null => {
    if (active?.activeTooltipIndex != null) return active.activeTooltipIndex;
    return null;
  };

  const handleMouseDown = (e: any) => {
    if (!e) return;
    const idx = getIdxFromActive(e);
    if (idx == null) return;
    setSelecting(true);
    setSelStart(idx);
    setSelEnd(idx);
  };

  const handleMouseMove = (e: any) => {
    if (!selecting || !e) return;
    const idx = getIdxFromActive(e);
    if (idx != null) setSelEnd(idx);
  };

  const handleMouseUp = () => {
    if (!selecting || selStart == null || selEnd == null) {
      setSelecting(false);
      return;
    }
    const i1 = Math.min(selStart, selEnd);
    const i2 = Math.max(selStart, selEnd);
    if (i2 - i1 < 2) {
      setSelecting(false);
      setSelStart(null);
      setSelEnd(null);
      return;
    }
    const slice = visibleData.slice(i1, i2 + 1);
    const { yMin, yMax } = computeYBounds(slice);
    // Map back to absolute indices if already zoomed
    const baseOffset = zoom ? zoom.x1 : 0;
    setZoom({ x1: baseOffset + i1, x2: baseOffset + i2, y1: yMin, y2: yMax });
    setSelecting(false);
    setSelStart(null);
    setSelEnd(null);
  };

  // Mouse wheel zoom
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const current = zoom ?? { x1: 0, x2: total - 1, y1: autoYMin, y2: autoYMax };
      const xSpan = current.x2 - current.x1;
      const ySpan = current.y2 - current.y1;
      const factor = e.deltaY > 0 ? 1.15 : 0.87; // scroll down = zoom out, up = zoom in

      if (e.shiftKey) {
        // Shift + scroll = pan left/right
        const shift = Math.round(xSpan * 0.1 * (e.deltaY > 0 ? 1 : -1));
        const nx1 = Math.max(0, current.x1 + shift);
        const nx2 = Math.min(total - 1, current.x2 + shift);
        if (nx2 - nx1 < 2) return;
        const slice = sampledData.slice(nx1, nx2 + 1);
        const { yMin, yMax } = computeYBounds(slice);
        setZoom({ x1: nx1, x2: nx2, y1: yMin, y2: yMax });
      } else {
        // Normal scroll = zoom in/out centered
        const xCenter = (current.x1 + current.x2) / 2;
        const yCenter = (current.y1 + current.y2) / 2;
        const newXHalf = (xSpan / 2) * factor;
        const newYHalf = (ySpan / 2) * factor;
        const nx1 = Math.max(0, Math.round(xCenter - newXHalf));
        const nx2 = Math.min(total - 1, Math.round(xCenter + newXHalf));
        if (nx2 - nx1 < 2) return;
        const slice = sampledData.slice(nx1, nx2 + 1);
        const { yMin: autoY1, yMax: autoY2 } = computeYBounds(slice);
        // Also zoom Y
        const ny1 = Math.min(autoY1, yCenter - newYHalf);
        const ny2 = Math.max(autoY2, yCenter + newYHalf);
        setZoom({ x1: nx1, x2: nx2, y1: ny1, y2: ny2 });
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoom, total, autoYMin, autoYMax, sampledData]);

  const selL = selStart != null && selEnd != null ? sampledData[Math.min(selStart, selEnd)]?.timestamp : undefined;
  const selR = selStart != null && selEnd != null ? sampledData[Math.max(selStart, selEnd)]?.timestamp : undefined;

  const zoomPct = isZoomed
    ? Math.round(((total - 1) / Math.max(1, zoom!.x2 - zoom!.x1)) * 100)
    : 100;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Portfolio NAV</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Starting $100.00 per strategy — live paper trading
          </p>
        </div>
        <div className="flex items-start gap-4">
          {ACTIVE_KEYS.map((k) => {
            const meta = STRATEGY_META[k];
            const latest = data[data.length - 1];
            const nav = latest?.[k] ?? 100;
            const pnl = nav - 100;
            return (
              <div key={k} className="text-right">
                <div className="text-xs text-gray-500">{meta.label}</div>
                <div className="text-sm font-mono font-bold" style={{ color: meta.color }}>
                  ${nav.toFixed(3)}
                </div>
                <div className={`text-xs ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {pnl >= 0 ? "+" : ""}{pnl.toFixed(3)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Zoom toolbar */}
      <div className="flex items-center gap-2 mb-2 text-xs text-gray-500">
        <span className="text-gray-600">
          {isZoomed
            ? `Zoom ${zoomPct}% · ${zoom!.x2 - zoom!.x1 + 1} of ${total} pts`
            : `${total} pts · drag to zoom · scroll to zoom · shift+scroll to pan`}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={() => {
              if (!zoom) return;
              const xSpan = zoom.x2 - zoom.x1;
              const nx1 = Math.max(0, zoom.x1 + Math.round(xSpan * 0.1));
              const nx2 = Math.min(total - 1, zoom.x2 - Math.round(xSpan * 0.1));
              if (nx2 - nx1 < 2) return;
              const slice = sampledData.slice(nx1, nx2 + 1);
              const { yMin, yMax } = computeYBounds(slice);
              setZoom({ x1: nx1, x2: nx2, y1: yMin, y2: yMax });
            }}
            className="px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 font-mono"
            title="Zoom in"
          >+</button>
          <button
            onClick={() => {
              const current = zoom ?? { x1: 0, x2: total - 1, y1: autoYMin, y2: autoYMax };
              const xSpan = current.x2 - current.x1;
              const nx1 = Math.max(0, current.x1 - Math.round(xSpan * 0.15));
              const nx2 = Math.min(total - 1, current.x2 + Math.round(xSpan * 0.15));
              const slice = sampledData.slice(nx1, nx2 + 1);
              const { yMin, yMax } = computeYBounds(slice);
              setZoom({ x1: nx1, x2: nx2, y1: yMin, y2: yMax });
            }}
            className="px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 font-mono"
            title="Zoom out"
          >−</button>
          <button
            onClick={reset}
            disabled={!isZoomed}
            className={`px-2 py-0.5 rounded font-mono transition-colors ${
              isZoomed
                ? "bg-emerald-800 hover:bg-emerald-700 text-emerald-200"
                : "bg-gray-800 text-gray-600 cursor-default"
            }`}
            title="Reset zoom"
          >↩ Reset</button>
        </div>
      </div>

      {sampledData.length < 2 ? (
        <div className="h-48 flex items-center justify-center text-gray-600">
          <div className="text-center">
            <div className="text-2xl mb-2">📊</div>
            <p>Collecting data... NAV chart will appear shortly</p>
          </div>
        </div>
      ) : (
        <div
          ref={containerRef}
          style={{ userSelect: "none", cursor: selecting ? "crosshair" : "default" }}
          onDoubleClick={reset}
        >
          <ResponsiveContainer width="100%" height={190}>
            <LineChart
              data={visibleData}
              margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis
                dataKey="timestamp"
                tickFormatter={(v: string) => {
                  try { return format(new Date(v), "HH:mm"); } catch { return ""; }
                }}
                tick={{ fill: "#6b7280", fontSize: 10 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
                minTickGap={40}
              />
              <YAxis
                domain={yDomain}
                tick={{ fill: "#6b7280", fontSize: 10 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                width={56}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                formatter={(value: string) =>
                  STRATEGY_META[value as keyof typeof STRATEGY_META]?.label ?? value
                }
                wrapperStyle={{ fontSize: 12 }}
              />
              <ReferenceLine y={100} stroke="#374151" strokeDasharray="4 4" />
              {selecting && selL && selR && (
                <ReferenceArea x1={selL} x2={selR} strokeOpacity={0.3} fill="#34d399" fillOpacity={0.1} />
              )}
              <Line type="monotone" dataKey="near_certain" stroke="#e879f9" strokeWidth={2.5} dot={false} activeDot={{ r: 6, fill: "#e879f9" }} isAnimationActive={false} />
              <Line type="monotone" dataKey="daily_updown" stroke="#fbbf24" strokeWidth={2.5} dot={false} activeDot={{ r: 6, fill: "#fbbf24" }} isAnimationActive={false} />
              <Line type="monotone" dataKey="weather" stroke="#38bdf8" strokeWidth={2.5} dot={false} activeDot={{ r: 6, fill: "#38bdf8" }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
