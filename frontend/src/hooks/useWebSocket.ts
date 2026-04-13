import { useEffect, useRef, useState, useCallback } from "react";
import { BotState, NavPoint } from "../types";

const WS_URL =
  typeof window !== "undefined"
    ? `ws://${window.location.hostname}:8000/ws`
    : "ws://localhost:8000/ws";

export type WsStatus = "connecting" | "connected" | "disconnected" | "error";

export function useWebSocket() {
  const [state, setState] = useState<BotState | null>(null);
  const [wsStatus, setWsStatus] = useState<WsStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelay = useRef(2000);
  // Accumulate full NAV history across all messages (initial = full DB, subsequent = deltas)
  const navHistoryRef = useRef<NavPoint[]>([]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setWsStatus("connecting");
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus("connected");
      reconnectDelay.current = 2000;
    };

    ws.onmessage = (ev) => {
      try {
        const data: BotState = JSON.parse(ev.data);
        if (data.type === "state_update") {
          // Merge incoming nav_history into our accumulated buffer (deduplicate by timestamp)
          if (data.nav_history?.length) {
            const existing = new Set(navHistoryRef.current.map((p) => p.timestamp));
            const newPoints = data.nav_history.filter((p) => !existing.has(p.timestamp));
            if (newPoints.length) {
              navHistoryRef.current = [...navHistoryRef.current, ...newPoints].sort(
                (a, b) => a.timestamp.localeCompare(b.timestamp)
              );
            }
          }
          setState({ ...data, nav_history: navHistoryRef.current });
        }
      } catch {
        // ignore malformed messages
      }
    };

    ws.onerror = () => {
      setWsStatus("error");
    };

    ws.onclose = () => {
      setWsStatus("disconnected");
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, 15000);
        connect();
      }, reconnectDelay.current);
    };
  }, []);

  // Periodic hard-reconnect every 60s to re-fetch full state from DB
  const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    connect();
    refreshTimer.current = setInterval(() => {
      wsRef.current?.close();
    }, 60_000);
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (refreshTimer.current) clearInterval(refreshTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { state, wsStatus };
}
