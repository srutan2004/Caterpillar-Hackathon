// Dashboard & Scenario Player widgets (§18 demo, §9.2 admin scenarios).
// Provides: ScenarioPlayer (start/stop edge simulations), DashboardStats (system overview),
// EvalSummary (evaluation results), FleetStatusBoard (fleet health snapshot).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useFormatters } from "../runtime/format";
import { StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

// ------------------------------------------------------------------ scenario player
interface Scenario {
  id: string;
  machine: string;
  duration_s: number;
  running: boolean;
}

const SPEED_DEFAULT = 1;

export function ScenarioPlayer({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["scenarios"],
    queryFn: () => api<Scenario[]>("/api/admin/scenarios"),
    refetchInterval: 5000,
  });
  const start = useMutation({
    mutationFn: (id: string) =>
      api(`/api/admin/scenarios/${id}/start?speed=${SPEED_DEFAULT}`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });
  const stop = useMutation({
    mutationFn: (id: string) =>
      api(`/api/admin/scenarios/${id}/stop`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });

  const scenarios = q.data ?? [];
  return (
    <Tile type={widget.type}>
      {!scenarios.length ? (
        <p className="muted">{t(q.isLoading ? "app.loading" : "app.empty")}</p>
      ) : (
        <ul className="scenario-list">
          {scenarios.map((sc) => {
            const tier: Tier = sc.running ? "normal" : "advisory";
            return (
              <li key={sc.id} className="scenario-item">
                <StatusBadge tier={tier} />
                <span className="strong">{sc.id.replace(/_/g, " ")}</span>
                <span className="muted small">{sc.machine}</span>
                <span className="muted small">{Math.round(sc.duration_s)}s</span>
                {sc.running ? (
                  <button type="button" onClick={() => stop.mutate(sc.id)} disabled={stop.isPending}>
                    {t("widget.scenario_player.stop")}
                  </button>
                ) : (
                  <button type="button" className="primary" onClick={() => start.mutate(sc.id)} disabled={start.isPending}>
                    {t("widget.scenario_player.start")}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Tile>
  );
}

// ------------------------------------------------------------------ dashboard stats
export function DashboardStats({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const machines = useQuery({
    queryKey: ["dashboard_machines"],
    queryFn: () => api<{ id: string; status: string; machine_class: string }[]>("/api/machines"),
  });
  const maintAlerts = useQuery({
    queryKey: ["dashboard_maint"],
    queryFn: () => api<{ id: string; tier: string }[]>("/api/maintenance/alerts"),
  });

  const machineList = machines.data ?? [];
  const alerts = maintAlerts.data ?? [];

  return (
    <Tile type={widget.type}>
      <div className="dashboard-grid">
        <div className="dash-stat">
          <span className="dash-stat-value">{machineList.length}</span>
          <span className="dash-stat-label">{t("widget.dashboard_stats.machines")}</span>
        </div>
        <div className="dash-stat">
          <span className="dash-stat-value">{machineList.filter((m) => m.status === "available").length}</span>
          <span className="dash-stat-label">{t("widget.dashboard_stats.available")}</span>
        </div>
        <div className="dash-stat">
          <span className="dash-stat-value">{alerts.length}</span>
          <span className="dash-stat-label">{t("widget.dashboard_stats.alerts")}</span>
        </div>
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------ eval summary
interface EvalMetric {
  name: string;
  value: number;
  target: number;
  passed: boolean;
}

interface EvalSuiteResult {
  suite: string;
  passed: boolean;
  duration_s: number;
  metrics: EvalMetric[];
}

export function EvalSummary({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const q = useQuery({
    queryKey: ["eval_latest"],
    queryFn: () => api<Record<string, EvalSuiteResult>>("/api/evals/latest"),
  });

  if (!q.data || q.isError) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(q.isError ? "error.forbidden" : "app.loading")}</p>
      </Tile>
    );
  }

  const suites = Object.values(q.data);
  const allPassed = suites.every((s) => s.passed);
  return (
    <Tile type={widget.type}>
      <p>
        <StatusBadge tier={allPassed ? "normal" : "warning"} />
        <span className="strong">
          {t(allPassed ? "widget.eval_summary.all_pass" : "widget.eval_summary.some_fail", {
            count: suites.length,
            pass: suites.filter((s) => s.passed).length,
          })}
        </span>
      </p>
      <table className="data-table">
        <thead>
          <tr>
            <th>{t("widget.eval_summary.suite")}</th>
            <th>{t("widget.eval_summary.status")}</th>
            <th>{t("widget.eval_summary.score")}</th>
          </tr>
        </thead>
        <tbody>
          {suites.map((s) => (
            <tr key={s.suite}>
              <td>{s.suite}</td>
              <td>
                <StatusBadge tier={s.passed ? "normal" : "warning"} />
              </td>
              <td>{f.num(s.duration_s, 1)}s</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Tile>
  );
}


// ------------------------------------------------------------------ fleet status board
interface FleetMachine {
  id: string;
  model: string;
  machine_class: string;
  status: string;
  powertrain: string;
}

export function FleetStatusBoard({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ["fleet_machines"],
    queryFn: () => api<FleetMachine[]>("/api/machines"),
    refetchInterval: 10000,
  });
  const machines = q.data ?? [];
  if (!machines.length) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(q.isLoading ? "app.loading" : "app.empty")}</p>
      </Tile>
    );
  }
  return (
    <Tile type={widget.type}>
      <table className="data-table">
        <thead>
          <tr>
            <th>{t("widget.fleet_status_board.id")}</th>
            <th>{t("widget.fleet_status_board.class")}</th>
            <th>{t("widget.fleet_status_board.status")}</th>
            <th>{t("widget.fleet_status_board.powertrain")}</th>
          </tr>
        </thead>
        <tbody>
          {machines.map((m) => {
            const tier: Tier = m.status === "available" ? "normal" : "caution";
            return (
              <tr key={m.id}>
                <td className="strong">{m.id}</td>
                <td>{t(`machine.class.${m.machine_class}`)}</td>
                <td>
                  <StatusBadge tier={tier} />
                  {t(`machine.status.${m.status}`)}
                </td>
                <td>{m.powertrain}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Tile>
  );
}
