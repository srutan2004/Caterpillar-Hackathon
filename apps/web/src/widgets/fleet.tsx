// Fleet / supervisor widgets: component health, charge-plan gantt, availability forecast and KPI tiles.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { PERCENT, useFormatters } from "../runtime/format";
import { useSelection } from "../runtime/selection";
import { LineChart, type Series } from "./chart";
import { StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

const RISK_TIER: Record<string, Tier> = { low: "normal", medium: "caution", high: "warning" };
const ms = (iso: string) => new Date(iso).getTime();

interface HealthRow {
  component: string;
  health_index: number;
  risk: { p_fail: number; band: string; horizon_h: number };
  rul: { rul_h_p50: number; rul_h_p10: number } | null;
  evidence: { layer: string; tier: string }[];
}

export function HealthList({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const machineId = useSelection((s) => s.machineId);
  const q = useQuery({
    queryKey: ["health", machineId],
    queryFn: () => api<{ components: HealthRow[] }>(`/api/machines/${encodeURIComponent(machineId as string)}/health`),
    enabled: !!machineId,
  });
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
        {q.data.components.map((c) => (
          <li key={c.component}>
            <StatusBadge tier={RISK_TIER[c.risk.band] ?? "normal"} />
            <span className="strong">{t(`maintenance.component.${c.component}`)}</span>
            <span>{t("widget.health_list.health", { pct: f.pct(c.health_index) })}</span>
            <span className="small muted">{t("widget.health_list.risk", { pct: f.pct(c.risk.p_fail), days: f.num(c.risk.horizon_h / HOURS_PER_DAY, 0) })}</span>
            {c.rul ? <span className="small muted">{t("widget.health_list.rul", { h: f.num(c.rul.rul_h_p50, 0) })}</span> : null}
          </li>
        ))}
      </ul>
    </Tile>
  );
}

interface ChargeSlot {
  machine_id: string;
  start: string;
  end: string;
  mode: string;
  soc: number;
}

export function Gantt({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const siteId = useSelection((s) => s.siteId);
  const plan = useMutation({
    mutationFn: () => api<{ plan: ChargeSlot[]; feasible: boolean; binding_constraint: string | null; chargers: number }>("/api/energy/charge-plan", { method: "POST", body: JSON.stringify({ site_id: siteId }) }),
  });
  const data = plan.data;
  const byMachine = new Map<string, ChargeSlot[]>();
  for (const slot of data?.plan ?? []) {
    byMachine.set(slot.machine_id, [...(byMachine.get(slot.machine_id) ?? []), slot]);
  }
  return (
    <Tile type={widget.type}>
      <button type="button" className="primary" disabled={!siteId || plan.isPending} onClick={() => plan.mutate()}>
        {t("widget.gantt.solve")}
      </button>
      {data ? (
        <>
          <p className="small">
            <StatusBadge tier={data.feasible ? "normal" : "caution"} />
            {t(data.feasible ? "widget.gantt.feasible" : "widget.gantt.infeasible", { constraint: t(`plan.constraint.${data.binding_constraint}`, { defaultValue: data.binding_constraint ?? "" }) })}
            <span className="sep" />
            {t("widget.gantt.chargers", { n: data.chargers })}
          </p>
          {[...byMachine.entries()].map(([machine, slots]) => {
            const series: Series[] = [{ id: machine, label: machine, role: "series_1", points: slots.map((s) => ({ x: ms(s.start), y: s.soc * PERCENT })) }];
            return (
              <div key={machine}>
                <p className="strong small">{machine}</p>
                <ol className="gantt-row">
                  {slots.map((s) => (
                    <li key={s.start} data-mode={s.mode} title={`${t(`widget.gantt.${s.mode}`)} ${f.time(s.start)}`}>
                      <span className="sr-only">{t(`widget.gantt.${s.mode}`)}</span>
                    </li>
                  ))}
                </ol>
                <LineChart series={series} formatX={(x) => f.time(new Date(x).toISOString())} formatY={(y) => f.pct(y / PERCENT)} yDomain={[0, PERCENT]} yLabel={t("widget.gantt.soc")} ariaLabel={t("widget.gantt.soc")} />
              </div>
            );
          })}
        </>
      ) : null}
      {plan.isError ? <p className="form-error">{t("app.error_generic")}</p> : null}
    </Tile>
  );
}

interface AvailabilityRow {
  date: string;
  machine_id: string;
  p_available: number;
  planned_downtime_h: number;
  risk_downtime_h: number;
}

export function AvailabilityChart({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const siteId = useSelection((s) => s.siteId);
  const q = useQuery({
    queryKey: ["availability", siteId],
    queryFn: () => api<AvailabilityRow[]>(`/api/fleet/availability${siteId ? `?site=${encodeURIComponent(siteId)}` : ""}`),
  });
  if (!q.data?.length) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(q.isLoading ? "app.loading" : "app.empty")}</p>
      </Tile>
    );
  }
  const byDate = new Map<string, number[]>();
  for (const row of q.data) {
    byDate.set(row.date, [...(byDate.get(row.date) ?? []), row.p_available]);
  }
  const series: Series[] = [
    {
      id: "fleet",
      label: t("widget.availability_chart.fleet"),
      role: "series_1",
      points: [...byDate.entries()].map(([date, values]) => ({ x: ms(date), y: (values.reduce((a, b) => a + b, 0) / values.length) * PERCENT })),
    },
  ];
  return (
    <Tile type={widget.type}>
      <LineChart
        series={series}
        formatX={(x) => f.day(new Date(x).toISOString())}
        formatY={(y) => f.pct(y / PERCENT)}
        yDomain={[0, PERCENT]}
        yLabel={t("widget.availability_chart.y")}
        ariaLabel={t("widget.availability_chart.title")}
      />
    </Tile>
  );
}

export function KpiTile({ widget, binding, props }: WidgetProps) {
  const f = useFormatters();
  const value = binding.value as number | null | undefined;
  const kind = String(props.kind ?? "number");
  const label = String(props.label_key ?? "widget.kpi_tile.title");
  const format = kind === "ratio" ? f.pct : kind === "money" ? f.money : kind === "minutes" ? f.minutes : (v: number | null | undefined) => f.num(v, 0);
  return (
    <Tile type={widget.type} titleKey={label}>
      <p className="gauge-value">{format(value ?? null)}</p>
    </Tile>
  );
}

const HOURS_PER_DAY = 24;
