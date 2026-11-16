// WS client (§9.3): authenticated, reconnects with the backoff schedule from bootstrap.refresh.
import { useEffect } from "react";

import { wsUrl, type WsMessage } from "../api/client";
import { useSession } from "../app/session";
import { useBootstrap } from "../app/bootstrap";
import { useLive } from "./live";

export function useMachineSocket(machineId: string | undefined): void {
  const token = useSession((s) => s.token);
  const boot = useBootstrap();
  const apply = useLive((s) => s.apply);
  const setConnected = useLive((s) => s.setConnected);
  const reset = useLive((s) => s.reset);
  const path = boot?.ws.machine_path;
  const backoff = boot?.refresh.ws_reconnect_ms as number[] | undefined;

  useEffect(() => {
    if (!machineId || !token || !path || !backoff) return undefined;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    reset();

    const connect = () => {
      socket = new WebSocket(wsUrl(path.replace("{machine_id}", machineId), token));
      socket.onopen = () => {
        attempt = 0;
        setConnected(true, machineId);
      };
      socket.onmessage = (ev) => {
        try {
          apply(JSON.parse(String(ev.data)) as WsMessage);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        setConnected(false, machineId);
        if (closed) return;
        const delay = backoff[Math.min(attempt, backoff.length - 1)];
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
      setConnected(false, null);
    };
  }, [machineId, token, path, backoff, apply, setConnected, reset]);
}
