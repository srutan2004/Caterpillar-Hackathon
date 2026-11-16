// Maintenance widgets (§10.13, §10.15.9): alert cards with lifecycle actions, sensor forecast cone, service due.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { routes } from "../api/routes";
import { resourceKey } from "../runtime/binding";
import { useFormatters } from "../runtime/format";
import { sensorKey } from "../runtime/i18n";
import { useSelection } from "../runtime/selection";
import { LineChart, type Series } from "./chart";
import { StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

const TIER: Record<string, Tier> = { monitor: "advisory", service_soon: "caution", stop: "warning" };
const ms = (iso: string) => new Date(iso).getTime();
const DETAIL_DIGITS = 2;
const NO_ALERTS: AlertRow[] = [];

interface Why {
  key: string;
  layer: string;
  tier: string;
  sensor_id: string | null;
  value: number | null;
  params: Record<string, number | string>;
}

interface AlertRow {
  id: string;
  machine_id: string;
  site_id?: string;
  component: string;
  tier: string;
  state: string;
  opened_at: string;
  updated_at: string;
  sensor_ids: string[];
  safe_to_continue: string | null;
  title_key: string | null;
  checks: string[];
  parts_detail: { part_no: string; description: string; stock: number; lead_time_days: number }[];
  est_repair: { hours: number; total_cost: number } | null;
  eta: { eta_h_p10: number; eta_h_p50: number; eta_h_p90: number | null; target_tier: string; sensor_id: string } | null;
  actions: string[];
  layers: string[];
  why: Why[];
  work_order_id: string | null;
  routing: Record<string, string | boolean>;
}

const ACTION_OF_STATE: Record<string, string> = {
  acknowledged: "ack",
  scheduled: "schedule",
  in_service: "start",
  resolved: "resolve",
  false_alarm: "false_alarm",
};

export function MaintenanceAlertCard({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const qc = useQueryClient();
  const alerts = (binding.value as AlertRow[] | undefined) ?? NO_ALERTS;
  const selected = useSelection((s) => s.alertId);
  const select = useSelection((s) => s.select);
  useEffect(() => {
    if (alerts.length && (!selected || !alerts.some((a) => a.id === selected))) select({ alertId: alerts[0].id, machineId: alerts[0].machine_id });
  }, [alerts, selected, select]);
  const act = useMutation({
    mutationFn: ({ id, path }: { id: string; path: string }) => api(path === "work-order" ? routes.workOrder(id) : routes.maintenanceAction(id, path), { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: resourceKey("maintenance_alerts") }),
  });
  if (!alerts.length) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(binding.status === "loading" ? "app.loading" : "widget.maintenance_alert_card.none")}</p>
      </Tile>
    );
  }
  return (
    <Tile type={widget.type}>
      <ul className="alert-cards">
        {alerts.map((a) => (
          <li key={a.id} className="maint-card" data-tier={TIER[a.tier]} data-selected={a.id === selected}>
            <button type="button" className="task-card-head" onClick={() => select({ alertId: a.id, machineId: a.machine_id })} aria-pressed={a.id === selected}>
              <StatusBadge tier={TIER[a.tier] ?? "advisory"} />
              <span className="strong">{t(`maintenance.tier.${a.tier}`)}</span>
              <span>{t(`maintenance.component.${a.component}`)}</span>
              <span className="muted small">{a.machine_id}</span>
              <span className="chip">{t(`maintenance.state.${a.state}`)}</span>
            </button>
            {a.title_key ? <p className="small">{t(a.title_key)}</p> : null}
            {a.eta ? (
              <p className="small">
                {t("widget.maintenance_alert_card.eta", {
                  tier: t(`maintenance.tier.${a.eta.target_tier}`),
                  p50: f.num(a.eta.eta_h_p50, 0),
                  p10: f.num(a.eta.eta_h_p10, 0),
                })}
              </p>
            ) : null}
            <ul className="why small">
              {a.why.map((w, idx) => (
                <li key={`${w.layer}-${w.sensor_id ?? ""}-${idx}`}>
                  {t(w.key, {
                    sensor: w.sensor_id ? t(sensorKey(w.sensor_id)) : "",
                    value: f.num(w.value),
                    ...Object.fromEntries(Object.entries(w.params).map(([k, v]) => [k, typeof v === "number" ? f.num(v, DETAIL_DIGITS) : t(`maintenance.tier.${v}`, { defaultValue: String(v) })])),
                  })}
                </li>
              ))}
            </ul>
            {a.safe_to_continue ? (
              <p className="small">
                <span className="strong">{t("widget.maintenance_alert_card.safe")}</span>
                <span className="sep" />
                {t(`maintenance.safe.${a.safe_to_continue}`)}
              </p>
            ) : null}
            {a.parts_detail.length ? (
              <p className="small muted">
                {t("widget.maintenance_alert_card.parts", {
                  list: a.parts_detail.map((p) => t("widget.maintenance_alert_card.part", { part: p.part_no, stock: p.stock, days: p.lead_time_days })).join(", "),
                })}
              </p>
            ) : null}
            {a.est_repair ? (
              <p className="small muted">{t("widget.maintenance_alert_card.repair", { hours: f.num(a.est_repair.hours), cost: f.money(a.est_repair.total_cost) })}</p>
            ) : null}
            <div className="row">
              {a.actions
                .filter((s) => ACTION_OF_STATE[s])
                .map((s) => (
                  <button key={s} type="button" disabled={act.isPending} onClick={() => act.mutate({ id: a.id, path: ACTION_OF_STATE[s] })}>
                    {t(`maintenance.action.${ACTION_OF_STATE[s]}`)}
                  </button>
                ))}
              <button type="button" className="primary" disabled={act.isPending || !!a.work_order_id} onClick={() => act.mutate({ id: a.id, path: "work-order" })}>
                {t(a.work_order_id ? "maintenance.action.work_order_done" : "maintenance.action.work_order")}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </Tile>
  );
}

interface Forecast {
  sensor_id: string;
  unit: string;
  thresholds: Record<string, number | null>;
  history: { ts: string; value: number }[];
  forecast: { ts: string; p10: number; p50: number; p90: number }[];
  etas: Record<string, { eta_h_p50: number; eta_h_p10: number }>;
}

interface AlertDetail {
  id: string;
  forecasts: Forecast[];
}

export function SensorForecastChart({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const alertId = useSelection((s) => s.alertId);
  const q = useQuery({ queryKey: ["maint_alert", alertId], queryFn: () => api<AlertDetail>(routes.maintenanceAlert(alertId as string)), enabled: !!alertId });
  const forecasts = q.data?.forecasts ?? [];
  if (!alertId || !forecasts.length) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(q.isLoading ? "app.loading" : "widget.sensor_forecast_chart.none")}</p>
      </Tile>
    );
  }
  return (
    <Tile type={widget.type}>
      {forecasts.map((fc) => {
        const series: Series[] = [
          { id: "history", label: t("widget.sensor_forecast_chart.history"), role: "series_1", points: fc.history.map((p) => ({ x: ms(p.ts), y: p.value })) },
          { id: "forecast", label: t("widget.sensor_forecast_chart.forecast"), role: "series_1", dashed: true, points: fc.forecast.map((p) => ({ x: ms(p.ts), y: p.p50 })) },
        ];
        const rules = Object.entries(fc.thresholds)
          .filter((e): e is [string, number] => e[1] !== null)
          .map(([tier, y]) => ({ y, tier: TIER[tier] ?? tier, label: t(`maintenance.tier.${tier}`) }));
        return (
          <div key={fc.sensor_id} className="forecast-block">
            <p className="strong">{t(sensorKey(fc.sensor_id))}</p>
            <LineChart
              series={series}
              band={fc.forecast.length ? { label: t("widget.sensor_forecast_chart.cone"), points: fc.forecast.map((p) => ({ x: ms(p.ts), lo: p.p10, hi: p.p90 })) } : undefined}
              rules={rules}
              formatX={(x) => f.day(new Date(x).toISOString())}
              formatY={(y) => `${f.num(y)} ${fc.unit}`}
              yLabel={fc.unit}
              ariaLabel={t(sensorKey(fc.sensor_id))}
            />
            <ul className="small">
              {Object.entries(fc.etas).map(([tier, e]) => (
                <li key={tier}>{t("widget.sensor_forecast_chart.eta", { tier: t(`maintenance.tier.${tier}`), p50: f.num(e.eta_h_p50, 0), p10: f.num(e.eta_h_p10, 0) })}</li>
              ))}
            </ul>
          </div>
        );
      })}
    </Tile>
  );
}

interface ServiceItem {
  item: string;
  remaining_h: number;
  severity_factor: number;
  overdue: boolean;
  due_soon: boolean;
  eta: string;
  est_h: number | null;
}

export function ServiceCountdown({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const machineId = useSelection((s) => s.machineId);
  const q = useQuery({ queryKey: ["service_due", machineId], queryFn: () => api<ServiceItem[]>(routes.serviceDue(machineId as string)), enabled: !!machineId });
  if (!machineId || !q.data) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(q.isLoading ? "app.loading" : "app.empty")}</p>
      </Tile>
    );
  }
  return (
    <Tile type={widget.type}>
      <p className="small muted">{machineId}</p>
      <ul className="service-list">
        {q.data.map((s) => {
          const tier: Tier = s.overdue ? "warning" : s.due_soon ? "caution" : "normal";
          return (
            <li key={s.item}>
              <StatusBadge tier={tier} />
              <span className="strong">{t(`service.item.${s.item}`)}</span>
              <span>
                {s.overdue
                  ? t("widget.service_countdown.overdue", { h: f.num(Math.abs(s.remaining_h), 0) })
                  : t("widget.service_countdown.due_in", { h: f.num(s.remaining_h, 0), day: f.day(s.eta) })}
              </span>
              {s.severity_factor > 1 ? <span className="small muted">{t("widget.service_countdown.severity", { x: f.num(s.severity_factor, DETAIL_DIGITS) })}</span> : null}
            </li>
          );
        })}
      </ul>
    </Tile>
  );
}
