// Operator day widgets (§10.3, §10.14, §10.15): everything renders /api/me/shift and planning endpoints.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { routes } from "../api/routes";
import { resourceKey } from "../runtime/binding";
import { PERCENT, useFormatters } from "../runtime/format";
import { useSelection } from "../runtime/selection";
import { LineChart, type Region, type Series } from "./chart";
import { Meter, StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

// ------------------------------------------------------------------ payload shapes (subset of /api/me/shift)
interface Factor {
  feature: string;
  key: string;
  minutes: number;
}

interface Estimate {
  p10_min: number;
  p50_min: number;
  p90_min: number;
  factors: Factor[];
  source: string;
  baseline_min?: number | null;
}

interface BestStart {
  id?: string;
  recommended_start: string;
  recommend_change: boolean;
  feasible: boolean;
  saving_vs_usual_min: number | null;
  duration_saving_vs_now_min: number | null;
  preconditions: string[];
  usual_p50_min: number | null;
  accepted_at?: string | null;
}

interface TaskCardData {
  id: string;
  type: string;
  quantity: number;
  unit: string;
  progress_qty: number | null;
  status: string;
  planned_start: string;
  planned_end: string;
  deadline: string | null;
  estimate?: Estimate;
  live?: { remaining_min_p50?: number; etc_p50?: string; etc_p10?: string; etc_p90?: string };
  best_start?: BestStart;
  energy?: { unit: string; can_finish: boolean | null; margin: number | null; recharge_min?: number | null; refuel_min?: number | null };
  maintenance?: { id: string; component: string; tier: string }[];
  actual?: { duration_min: number | null };
}

interface Shift {
  now: string;
  machine_id: string | null;
  site_id: string | null;
  shift: { start: string; end: string };
  weather: { ts: string; temp_c: number | null; rain_mm: number | null; gust_ms: number | null }[];
  readiness: Readiness | null;
  walkaround: { result: string; blocks_start: boolean } | null;
  tasks: TaskCardData[];
  pacing: Pacing;
}

interface Readiness {
  score: number;
  band: string;
  deductions: { component: string; points: number; key: string }[];
  blocks_start: boolean;
}

interface Pacing {
  benchmark: { ts: string; pct: number }[];
  actual: { ts: string; pct: number }[];
  done_pct: number;
  expected_pct: number;
  gap_pct: number;
}

const WEATHER_HOURS = 8;
const BAND_TIER: Record<string, Tier> = { go: "normal", caution: "caution", hold: "warning" };
const MAINT_TIER: Record<string, Tier> = { monitor: "advisory", service_soon: "caution", stop: "warning" };
const ms = (iso: string) => new Date(iso).getTime();

function useShift(binding: WidgetProps["binding"]): Shift | undefined {
  return binding.value as Shift | undefined;
}

function Empty({ type, status }: { type: string; status: string }) {
  const { t } = useTranslation();
  return (
    <Tile type={type} tone={status === "error" ? "error" : undefined}>
      <p className="muted">{t(status === "loading" ? "app.loading" : status === "error" ? "app.error_generic" : "app.empty")}</p>
    </Tile>
  );
}

// ------------------------------------------------------------------ TaskTimeline (+ task cards, weather strip)
export function TaskTimeline({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const shift = useShift(binding);
  const selected = useSelection((s) => s.taskId);
  const select = useSelection((s) => s.select);
  const firstOpen = shift?.tasks.find((x) => x.status !== "completed")?.id ?? null;
  useEffect(() => {
    if (shift && (!selected || !shift.tasks.some((x) => x.id === selected))) select({ taskId: firstOpen, machineId: shift.machine_id });
  }, [shift, selected, firstOpen, select]);
  if (!shift) return <Empty type={widget.type} status={binding.status} />;
  return (
    <Tile type={widget.type}>
      <p className="small muted">
        {t("widget.task_timeline.shift", { start: f.time(shift.shift.start), end: f.time(shift.shift.end), machine: shift.machine_id ?? "—" })}
      </p>
      <ol className="weather-strip" aria-label={t("widget.task_timeline.weather")}>
        {shift.weather.slice(0, WEATHER_HOURS).map((w) => (
          <li key={w.ts}>
            <span className="strong">{f.time(w.ts)}</span>
            <span>{t("widget.task_timeline.temp", { v: f.num(w.temp_c, 0) })}</span>
            <span>{t("widget.task_timeline.rain", { v: f.num(w.rain_mm) })}</span>
            <span>{t("widget.task_timeline.gust", { v: f.num(w.gust_ms, 0) })}</span>
          </li>
        ))}
      </ol>
      {shift.tasks.length === 0 ? <p className="muted">{t("widget.task_timeline.none")}</p> : null}
      <ul className="task-list">
        {shift.tasks.map((task) => (
          <TaskCard key={task.id} task={task} selected={task.id === selected} onSelect={() => select({ taskId: task.id, machineId: shift.machine_id })} />
        ))}
      </ul>
    </Tile>
  );
}

function TaskCard({ task, selected, onSelect }: { task: TaskCardData; selected: boolean; onSelect: () => void }) {
  const { t } = useTranslation();
  const f = useFormatters();
  const done = task.progress_qty ?? 0;
  const e = task.estimate;
  const b = task.best_start;
  const energyTier: Tier = task.energy?.can_finish === false ? "caution" : "normal";
  return (
    <li className="task-card" data-selected={selected} data-status={task.status}>
      <button type="button" className="task-card-head" onClick={onSelect} aria-pressed={selected}>
        <span className="strong">{t(`task.type.${task.type}`)}</span>
        <span className="muted small">{task.id}</span>
        <span className="chip">{t(`task.status.${task.status}`)}</span>
      </button>
      <p className="small">
        {t("widget.task_timeline.window", { start: f.time(task.planned_start), end: f.time(task.planned_end) })}
        {task.deadline ? (
          <>
            <span className="sep" />
            {t("widget.task_timeline.deadline", { time: f.time(task.deadline) })}
          </>
        ) : null}
      </p>
      <Meter fraction={task.quantity ? done / task.quantity : 0} tier="normal" label={t("widget.task_timeline.progress", { done: f.num(done, 0), total: f.num(task.quantity, 0), unit: t(`unit.${task.unit}`) })} />
      <p className="small">{t("widget.task_timeline.progress", { done: f.num(done, 0), total: f.num(task.quantity, 0), unit: t(`unit.${task.unit}`) })}</p>
      {task.actual?.duration_min ? <p className="small">{t("widget.task_timeline.took", { d: f.minutes(task.actual.duration_min) })}</p> : null}
      {e ? (
        <div className="etc">
          <p>
            <span className="strong">{t("widget.task_timeline.etc", { p50: f.minutes(e.p50_min) })}</span>
            <span className="sep" />
            <span className="muted">{t("widget.task_timeline.band", { p10: f.minutes(e.p10_min), p90: f.minutes(e.p90_min) })}</span>
          </p>
          {task.live?.etc_p50 ? <p className="small">{t("widget.task_timeline.live_etc", { time: f.time(task.live.etc_p50) })}</p> : null}
          <ul className="factor-chips">
            {e.factors.map((x) => (
              <li key={x.feature} data-sign={x.minutes > 0 ? "slower" : "faster"}>
                {t("widget.task_timeline.factor", { factor: t(x.key), minutes: f.minutes(Math.abs(x.minutes)), sign: t(x.minutes > 0 ? "sign.plus" : "sign.minus") })}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="chips">
        {b ? (
          <span className="chip" data-kind="best_start" data-change={b.recommend_change}>
            {b.recommend_change
              ? t("widget.task_timeline.best_start", { time: f.time(b.recommended_start) })
              : t("widget.task_timeline.start_now")}
            {b.saving_vs_usual_min !== null && b.saving_vs_usual_min > 0 ? (
              <>
                <span className="sep" />
                {t("widget.task_timeline.vs_usual", { minutes: f.minutes(b.saving_vs_usual_min) })}
              </>
            ) : null}
            {b.accepted_at ? (
              <>
                <span className="sep" />
                {t("widget.task_timeline.accepted")}
              </>
            ) : null}
          </span>
        ) : null}
        {task.energy && task.energy.can_finish !== null ? (
          <span className="chip" data-kind="energy" data-tier={energyTier}>
            <StatusBadge tier={energyTier} />
            {task.energy.can_finish
              ? t("widget.task_timeline.energy_ok", { margin: f.pct(task.energy.margin) })
              : task.energy.recharge_min
                ? t("widget.task_timeline.energy_charge", { minutes: f.minutes(task.energy.recharge_min) })
                : t("widget.task_timeline.energy_refuel", { minutes: f.minutes(task.energy.refuel_min ?? 0) })}
          </span>
        ) : null}
        {(task.maintenance ?? []).map((m) => (
          <span key={m.id} className="chip" data-kind="maintenance">
            <StatusBadge tier={MAINT_TIER[m.tier] ?? "advisory"} />
            {t("widget.task_timeline.maintenance", { component: t(`maintenance.component.${m.component}`), tier: t(`maintenance.tier.${m.tier}`) })}
          </span>
        ))}
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ PacingGauge
export function PacingGauge({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const p = binding.value as Pacing | undefined;
  if (!p) return <Empty type={widget.type} status={binding.status} />;
  const series: Series[] = [
    { id: "benchmark", label: t("widget.pacing_gauge.benchmark"), role: "reference", dashed: true, points: p.benchmark.map((x) => ({ x: ms(x.ts), y: x.pct })) },
    { id: "actual", label: t("widget.pacing_gauge.actual"), role: "series_1", points: p.actual.map((x) => ({ x: ms(x.ts), y: x.pct })) },
  ];
  const tier: Tier = p.gap_pct < 0 ? "caution" : "normal";
  return (
    <Tile type={widget.type}>
      <p className="gauge-value">{f.pct(p.done_pct / PERCENT)}</p>
      <p className="small">
        {t("widget.pacing_gauge.expected", { pct: f.pct(p.expected_pct / PERCENT) })}
        <span className="sep" />
        <StatusBadge tier={tier} />
        {t(p.gap_pct < 0 ? "widget.pacing_gauge.behind" : "widget.pacing_gauge.on_track", { pct: f.pct(Math.abs(p.gap_pct) / PERCENT) })}
      </p>
      <LineChart
        series={series}
        formatX={(x) => f.time(new Date(x).toISOString())}
        formatY={(y) => f.pct(y / PERCENT)}
        yDomain={[0, PERCENT]}
        yLabel={t("widget.pacing_gauge.y")}
        ariaLabel={t("widget.pacing_gauge.title")}
      />
    </Tile>
  );
}

// ------------------------------------------------------------------ ReadinessBadge
export function ReadinessBadge({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const r = binding.value as Readiness | null | undefined;
  if (!r) return <Empty type={widget.type} status={binding.status} />;
  const tier = BAND_TIER[r.band] ?? "caution";
  return (
    <Tile type={widget.type}>
      <p className="gauge-value">{f.num(r.score, 0)}</p>
      <p>
        <StatusBadge tier={tier} />
        <span className="strong">{t(`readiness.band.${r.band}`)}</span>
      </p>
      {r.blocks_start ? <p className="small strong">{t("readiness.blocked")}</p> : null}
      <ul className="deductions small">
        {r.deductions.map((d) => (
          <li key={d.component}>{t("readiness.deduction", { what: t(d.key), points: f.num(d.points, 0) })}</li>
        ))}
      </ul>
    </Tile>
  );
}

// ------------------------------------------------------------------ start-time recommendation (selected task)
interface Precondition {
  kind: string;
  key: string;
  minutes?: number;
  target_soc?: number;
  station_id?: string;
  start?: string;
  end?: string;
  during?: string | null;
  alert_id?: string;
  component?: string;
  technician_slot?: { start: string; technician_id: string } | null;
}

interface CurvePoint {
  start: string;
  p10_min: number;
  p50_min: number;
  p90_min: number;
  feasible: boolean;
  violations: string[];
}

interface Recommendation {
  task_id: string;
  recommended_start: string;
  recommend_change: boolean;
  now: { start: string; p50_min: number };
  duration: { p50_min: number; p10_min: number; p90_min: number };
  usual_duration: { p50_min: number } | null;
  saving_vs_usual_min: number | null;
  duration_saving_vs_now_min: number | null;
  preconditions: Precondition[];
  factors: Factor[];
  binding: string[];
  curve: CurvePoint[];
  accepted_at?: string | null;
}

function useRecommendation(): { taskId: string | null; rec: Recommendation | undefined; status: string } {
  const taskId = useSelection((s) => s.taskId);
  const q = useQuery({
    queryKey: ["start_rec", taskId],
    queryFn: () => api<Recommendation>(routes.startRecommendation(taskId as string)),
    enabled: !!taskId,
  });
  return { taskId, rec: q.data, status: q.isError ? "error" : q.isLoading ? "loading" : "ready" };
}

function infeasibleRegions(curve: CurvePoint[], label: (v: string[]) => string): Region[] {
  const out: Region[] = [];
  let start: CurvePoint | null = null;
  curve.forEach((p, i) => {
    if (!p.feasible && !start) start = p;
    const next = curve[i + 1];
    if (start && (p.feasible || !next)) {
      // the region runs from the first infeasible start to the next feasible one (or the end of the grid)
      out.push({ x0: ms(start.start), x1: ms(p.start), label: label(start.violations) });
      start = null;
    }
  });
  return out;
}

export function StartTimeCurve({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const { rec, status, taskId } = useRecommendation();
  if (!taskId || !rec) return <Empty type={widget.type} status={taskId ? status : "empty"} />;
  const pts = rec.curve;
  const series: Series[] = [{ id: "p50", label: t("widget.start_time_curve.p50"), role: "series_1", points: pts.map((p) => ({ x: ms(p.start), y: p.p50_min })) }];
  const markers = [
    { x: ms(rec.now.start), label: t("widget.start_time_curve.now"), kind: "now" },
    { x: ms(rec.recommended_start), label: t("widget.start_time_curve.recommended"), kind: "recommended" },
  ];
  const rules = rec.usual_duration ? [{ y: rec.usual_duration.p50_min, label: t("widget.start_time_curve.usual"), tier: "usual" }] : [];
  return (
    <Tile type={widget.type}>
      <p>
        <span className="strong">
          {rec.recommend_change
            ? t("widget.start_time_curve.headline_change", { time: f.time(rec.recommended_start), minutes: f.minutes(rec.duration_saving_vs_now_min) })
            : t("widget.start_time_curve.headline_keep")}
        </span>
        {rec.saving_vs_usual_min !== null ? (
          <>
            <span className="sep" />
            {t("widget.start_time_curve.vs_usual", { minutes: f.minutes(rec.saving_vs_usual_min) })}
          </>
        ) : null}
      </p>
      <LineChart
        series={series}
        band={{ label: t("widget.start_time_curve.band"), points: pts.map((p) => ({ x: ms(p.start), lo: p.p10_min, hi: p.p90_min })) }}
        rules={rules}
        markers={markers}
        regions={infeasibleRegions(pts, (v) => v.map((x) => t(`plan.constraint.${x}`)).join(", "))}
        formatX={(x) => f.time(new Date(x).toISOString())}
        formatY={(y) => f.minutes(y)}
        yLabel={t("widget.start_time_curve.y")}
        ariaLabel={t("widget.start_time_curve.title")}
      />
      {rec.binding.length ? <p className="small muted">{t("widget.start_time_curve.binding", { list: rec.binding.map((x) => t(`plan.constraint.${x}`)).join(", ") })}</p> : null}
    </Tile>
  );
}

// ------------------------------------------------------------------ FactorBars (why the recommended start differs)
export function FactorBars({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const { rec, status, taskId } = useRecommendation();
  if (!taskId || !rec) return <Empty type={widget.type} status={taskId ? status : "empty"} />;
  const max = Math.max(1, ...rec.factors.map((x) => Math.abs(x.minutes)));
  return (
    <Tile type={widget.type}>
      {rec.factors.length === 0 ? <p className="muted">{t("widget.factor_bars.none")}</p> : null}
      <ul className="factor-bars">
        {rec.factors.map((x) => (
          <li key={x.feature} data-sign={x.minutes > 0 ? "slower" : "faster"} title={t(x.key)}>
            <span className="factor-label">{t(x.key)}</span>
            <span className="factor-track">
              <span className="factor-fill" style={{ width: `${(Math.abs(x.minutes) / max) * PERCENT}%` }} />
            </span>
            <span className="factor-value">{t("widget.factor_bars.value", { sign: t(x.minutes > 0 ? "sign.plus" : "sign.minus"), minutes: f.minutes(Math.abs(x.minutes)) })}</span>
          </li>
        ))}
      </ul>
    </Tile>
  );
}

// ------------------------------------------------------------------ PreconditionChecklist + Accept
export function PreconditionChecklist({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const qc = useQueryClient();
  const { rec, status, taskId } = useRecommendation();
  const accept = useMutation({
    mutationFn: () => api<{ charger_reservations: unknown[] }>(routes.acceptRecommendation(taskId as string), { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["start_rec", taskId] });
      void qc.invalidateQueries({ queryKey: resourceKey("shift") });
    },
  });
  if (!taskId || !rec) return <Empty type={widget.type} status={taskId ? status : "empty"} />;
  return (
    <Tile type={widget.type}>
      {rec.preconditions.length === 0 ? <p className="muted">{t("widget.precondition_checklist.none")}</p> : null}
      <ul className="preconditions">
        {rec.preconditions.map((p) => (
          <li key={`${p.kind}-${p.alert_id ?? p.station_id ?? ""}`} data-kind={p.kind}>
            <span className="strong">
              {t(p.key, {
                minutes: f.minutes(p.minutes ?? 0),
                soc: f.pct(p.target_soc ?? 0),
                station: p.station_id ?? "",
                component: p.component ? t(`maintenance.component.${p.component}`) : "",
              })}
            </span>
            {p.start ? <span className="small muted">{t("widget.precondition_checklist.when", { start: f.time(p.start), end: f.time(p.end) })}</span> : null}
            {p.during ? <span className="small muted">{t(`precondition.during.${p.during}`)}</span> : null}
            {p.technician_slot ? <span className="small muted">{t("widget.precondition_checklist.slot", { time: f.time(p.technician_slot.start) })}</span> : null}
          </li>
        ))}
      </ul>
      <button type="button" className="primary" disabled={accept.isPending || !!rec.accepted_at || accept.isSuccess} onClick={() => accept.mutate()}>
        {t(rec.accepted_at || accept.isSuccess ? "widget.precondition_checklist.accepted" : "widget.precondition_checklist.accept")}
      </button>
      {accept.isError ? <p className="form-error">{t("app.error_generic")}</p> : null}
    </Tile>
  );
}

// ------------------------------------------------------------------ Walkaround (server checklist + photos)
interface WalkItem {
  id: string;
  label_key: string;
  critical: boolean;
  photo: "none" | "optional" | "on_issue";
}

interface WalkaroundCfg {
  items: WalkItem[];
  time_budget_s: number;
  latest: { result: string; blocks_start: boolean } | null;
}

export function Walkaround({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const machineId = useSelection((s) => s.machineId);
  const q = useQuery({ queryKey: ["walkaround", machineId], queryFn: () => api<WalkaroundCfg>(routes.walkaround(machineId as string)), enabled: !!machineId });
  const [state, setState] = useState<Record<string, { status: "ok" | "issue"; photo_uri?: string }>>({});
  const submit = useMutation({
    mutationFn: () =>
      api<{ result: string }>(routes.walkaround(machineId as string), {
        method: "POST",
        body: JSON.stringify({ items: (q.data?.items ?? []).map((i) => ({ id: i.id, status: state[i.id]?.status ?? "ok", photo_uri: state[i.id]?.photo_uri })) }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["walkaround", machineId] });
      void qc.invalidateQueries({ queryKey: resourceKey("shift") });
    },
  });
  const upload = async (id: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const res = await api<{ uri: string }>(routes.walkaroundPhoto(machineId as string), { method: "POST", body });
    setState((s) => ({ ...s, [id]: { status: "issue", photo_uri: res.uri } }));
  };
  if (!machineId || !q.data) return <Empty type={widget.type} status={machineId ? (q.isError ? "error" : "loading") : "empty"} />;
  const latest = q.data.latest;
  const missingPhoto = q.data.items.some((i) => state[i.id]?.status === "issue" && i.photo === "on_issue" && !state[i.id]?.photo_uri);
  return (
    <Tile type={widget.type}>
      {latest ? (
        <p className="small">
          <StatusBadge tier={latest.result === "ok" ? "normal" : latest.result === "critical" ? "warning" : "caution"} />
          {t(`walkaround.result.${latest.result}`)}
          {latest.blocks_start ? (
            <>
              <span className="sep" />
              {t("walkaround.blocks_start")}
            </>
          ) : null}
        </p>
      ) : (
        <p className="small muted">{t("walkaround.budget", { s: q.data.time_budget_s })}</p>
      )}
      <ul className="checklist">
        {q.data.items.map((i) => {
          const s = state[i.id]?.status ?? "ok";
          return (
            <li key={i.id} data-status={s}>
              <span>
                {t(i.label_key)}
                {i.critical ? <span className="small muted">{t("walkaround.critical")}</span> : null}
              </span>
              <span className="toggle">
                {(["ok", "issue"] as const).map((v) => (
                  <button key={v} type="button" aria-pressed={s === v} onClick={() => setState((st) => ({ ...st, [i.id]: { ...st[i.id], status: v } }))}>
                    {t(`walkaround.status_${v}`)}
                  </button>
                ))}
              </span>
              {s === "issue" && i.photo !== "none" ? (
                <label className="small">
                  {t(state[i.id]?.photo_uri ? "walkaround.photo_added" : "walkaround.add_photo")}
                  <input type="file" accept="image/*" capture="environment" onChange={(e) => e.target.files?.[0] && void upload(i.id, e.target.files[0])} />
                </label>
              ) : null}
            </li>
          );
        })}
      </ul>
      <button type="button" className="primary" disabled={submit.isPending || missingPhoto} onClick={() => submit.mutate()}>
        {t("walkaround.submit")}
      </button>
      {missingPhoto ? <p className="small muted">{t("walkaround.photo_required")}</p> : null}
      {submit.isSuccess ? <p className="small">{t(`walkaround.result.${submit.data.result}`)}</p> : null}
      {submit.isError ? <p className="form-error">{t("app.error_generic")}</p> : null}
    </Tile>
  );
}

// ------------------------------------------------------------------ CabNotes (push-to-talk → STT → tags)
interface Note {
  id: string;
  ts: string;
  text: string;
  tags: string[];
}

export function CabNotes({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const qc = useQueryClient();
  const machineId = useSelection((s) => s.machineId);
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const send = useMutation({
    mutationFn: (audio?: Blob) => {
      const body = new FormData();
      if (text.trim()) body.append("text", text.trim());
      if (machineId) body.append("machine_id", machineId);
      if (audio) body.append("audio", audio, "note.webm");
      return api<Note>(routes.notes(), { method: "POST", body });
    },
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: resourceKey("notes") });
    },
  });
  const toggleRecord = async () => {
    if (recording) {
      recorder.current?.stop();
      setRecording(false);
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    chunks.current = [];
    rec.ondataavailable = (e) => chunks.current.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((tr) => tr.stop());
      send.mutate(new Blob(chunks.current, { type: rec.mimeType }));
    };
    recorder.current = rec;
    rec.start();
    setRecording(true);
  };
  const notes = (binding.value as Note[] | undefined) ?? [];
  return (
    <Tile type={widget.type}>
      <textarea value={text} onChange={(e) => setText(e.target.value)} aria-label={t("widget.cab_notes.placeholder")} placeholder={t("widget.cab_notes.placeholder")} />
      <div className="row">
        <button type="button" className="primary" disabled={!text.trim() || send.isPending} onClick={() => send.mutate(undefined)}>
          {t("widget.cab_notes.save")}
        </button>
        {typeof MediaRecorder !== "undefined" ? (
          <button type="button" aria-pressed={recording} onClick={() => void toggleRecord()}>
            {t(recording ? "widget.cab_notes.stop" : "widget.cab_notes.talk")}
          </button>
        ) : null}
      </div>
      {send.isError ? <p className="form-error">{t("widget.cab_notes.stt_unavailable")}</p> : null}
      <ul className="notes small">
        {notes.map((n) => (
          <li key={n.id}>
            <span className="muted">{f.time(n.ts)}</span>
            <span className="sep" />
            {n.text}
            {n.tags.map((tag) => (
              <span key={tag} className="chip">
                {t(`note.tag.${tag}`)}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </Tile>
  );
}
