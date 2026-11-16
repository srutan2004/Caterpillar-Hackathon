// Binding resolver (§14): `bind` strings from layout YAML → live values or REST resources.
//   state[.path] | alerts | advisory   → live store (WebSocket)
//   resource:<name>[.path]             → REST resource (TanStack Query)
//   app.<path>                         → bootstrap
//   form:<id> | screen:<id>            → identifiers passed through to the widget
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { useBootstrap } from "../app/bootstrap";
import { getPath, useLive } from "./live";
import { secondsToMs } from "./time";

// API routes (not domain data) that back `resource:` bindings. Resources for later phases resolve to
// "pending" until their endpoint exists.
const RESOURCE_ROUTES: Record<string, string> = {
  machines: "/api/machines",
  llm_status: "/api/admin/llm/status",
  config_validation: "/api/admin/config/validate",
  shift: "/api/me/shift",
  maintenance_alerts: "/api/maintenance/alerts",
  incidents: "/api/incidents",
  notes: "/api/notes",
  idle_summary: "/api/behavior/idle-summary",
  anomalies: "/api/behavior/anomalies",
  training_me: "/api/training/me",
  compliance_seatbelt: "/api/compliance/seatbelt",
  compliance_ppe: "/api/compliance/ppe",
  maintenance_windows: "/api/maintenance/windows",
  scenarios: "/api/admin/scenarios",
  evals_latest: "/api/evals/latest",
  fleet_machines: "/api/fleet/machines",
};

/** Query key of a resource binding, so widgets can invalidate what they changed. */
export const resourceKey = (name: string): unknown[] => ["resource", RESOURCE_ROUTES[name]];

export interface Binding {
  value: unknown;
  status: "ready" | "loading" | "pending" | "error";
}

function parse(bind: string | null | undefined): { kind: string; name: string; path: string } {
  if (!bind) return { kind: "none", name: "", path: "" };
  const colon = bind.indexOf(":");
  if (colon > 0) {
    const [head, ...rest] = bind.slice(colon + 1).split(".");
    return { kind: bind.slice(0, colon), name: head, path: rest.join(".") };
  }
  const [head, ...rest] = bind.split(".");
  return { kind: head === "state" || head === "alerts" || head === "advisory" ? "live" : head, name: head, path: rest.join(".") };
}

export function useBinding(bind: string | null | undefined): Binding {
  const boot = useBootstrap();
  const p = parse(bind);
  const route = p.kind === "resource" ? RESOURCE_ROUTES[p.name] : undefined;
  const live = useLive((s) => (p.kind === "live" ? (s[p.name as "state" | "alerts" | "advisory"] as unknown) : undefined));
  // resources refresh on the cadence named `<resource>_s` in bootstrap.refresh, when present
  const refreshS = p.kind === "resource" ? (boot?.refresh[`${p.name}_s`] as number | undefined) : undefined;
  const query = useQuery({
    queryKey: ["resource", route],
    queryFn: () => api<unknown>(route as string),
    enabled: !!route,
    refetchInterval: refreshS ? secondsToMs(refreshS) : false,
  });

  switch (p.kind) {
    case "none":
      return { value: null, status: "ready" };
    case "live":
      return { value: p.path ? getPath(live, p.path) : live, status: "ready" };
    case "app":
      return { value: getPath(boot, p.path), status: "ready" };
    case "form":
    case "screen":
      return { value: p.name, status: "ready" };
    case "resource":
      if (!route) return { value: undefined, status: "pending" };
      if (query.isError) return { value: undefined, status: "error" };
      if (query.isLoading) return { value: undefined, status: "loading" };
      return { value: p.path ? getPath(query.data, p.path) : query.data, status: "ready" };
    default:
      return { value: undefined, status: "pending" };
  }
}
