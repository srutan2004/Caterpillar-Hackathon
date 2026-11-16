// Live store fed by the WebSocket (§14 binding resolver). State diffs apply to dotted paths.
import { create } from "zustand";

import type { WsMessage } from "../api/client";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

interface LiveState {
  connected: boolean;
  machineId: string | null;
  state: Record<string, Json>;
  alerts: Json[];
  advisory: Json | null;
  lastNotice: string | null;
  setConnected: (connected: boolean, machineId: string | null) => void;
  apply: (msg: WsMessage) => void;
  reset: () => void;
}

export function setPath(target: Record<string, Json>, path: string, value: Json): Record<string, Json> {
  const parts = path.split(".");
  const root: Record<string, Json> = { ...target };
  let node: Record<string, Json> = root;
  parts.slice(0, -1).forEach((part) => {
    const next = node[part];
    const copy: Record<string, Json> = typeof next === "object" && next !== null && !Array.isArray(next) ? { ...next } : {};
    node[part] = copy;
    node = copy;
  });
  node[parts[parts.length - 1]] = value;
  return root;
}

export function getPath(source: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => {
    if (node && typeof node === "object") return (node as Record<string, unknown>)[part];
    return undefined;
  }, source);
}

export const useLive = create<LiveState>((set) => ({
  connected: false,
  machineId: null,
  state: {},
  alerts: [],
  advisory: null,
  lastNotice: null,
  setConnected: (connected, machineId) => set({ connected, machineId }),
  reset: () => set({ state: {}, alerts: [], advisory: null, lastNotice: null }),
  apply: (msg) =>
    set((s) => {
      switch (msg.type) {
        case "state_diff": {
          let next = msg.full ? {} : s.state;
          for (const [path, value] of Object.entries(msg.changes)) next = setPath(next, path, value as Json);
          return { state: next };
        }
        case "alert": {
          const others = s.alerts.filter((a) => getPath(a, "alert.id") !== msg.event.alert.id);
          return { alerts: msg.event.phase === "clear" ? others : [...others, msg.event as unknown as Json] };
        }
        case "advisory":
          return { advisory: msg.advisory as unknown as Json };
        case "notice":
          return { lastNotice: msg.code };
        default:
          return {};
      }
    }),
}));
