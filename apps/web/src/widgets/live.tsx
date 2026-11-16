// Live cockpit widgets (§10.4, §14). Every threshold arrives resolved from the manifest via the layout API.
import { useTranslation } from "react-i18next";

import { useBootstrap } from "../app/bootstrap";
import { getPath, useLive } from "../runtime/live";
import { useFormatters } from "../runtime/format";
import { formatValue, type UnitsConfig } from "../runtime/units";
import { Meter, StatusBadge, bandTier, lowTier, withinTier, worst, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

function useUnits(): { units: UnitsConfig; lang: string } {
  const boot = useBootstrap();
  const { i18n } = useTranslation();
  return { units: (boot?.units ?? { system: "", quantities: {} }) as unknown as UnitsConfig, lang: i18n.language };
}

// ------------------------------------------------------------------ gauge (sensor meter)
export function Gauge({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const sensor = getPath(widget.resolved, "sensor") as { id: string; unit?: string; range?: [number, number]; bands?: Record<string, [number, number]> } | undefined;
  const value = binding.value as number | undefined;
  const titleKey = sensor ? `sensor.${sensor.id.replace(/\./g, "__")}` : undefined;
  if (value === undefined || value === null || !sensor) {
    return (
      <Tile type={widget.type} titleKey={titleKey}>
        <p className="muted">{t("app.empty")}</p>
      </Tile>
    );
  }
  const [lo, hi] = sensor.range ?? [0, value || 1];
  const tier = bandTier(value, sensor.bands);
  return (
    <Tile type={widget.type} titleKey={titleKey}>
      <p className="gauge-value">
        {Math.round(value)}
        <span className="gauge-unit">{sensor.unit}</span>
      </p>
      <Meter fraction={(value - lo) / (hi - lo)} tier={tier} label={`${Math.round(value)} ${sensor.unit ?? ""}`} />
      <StatusBadge tier={tier} />
    </Tile>
  );
}

// ------------------------------------------------------------------ stability dial
export function StabilityDial({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const { units, lang } = useUnits();
  const margin = binding.value as number | undefined;
  const bands = getPath(widget.resolved, "bands") as Record<string, number> | undefined;
  const stab = useLive((s) => s.state.stability) as { limiting_axis?: string; hint?: string } | undefined;
  if (margin === undefined || margin === null) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t("app.empty")}</p>
      </Tile>
    );
  }
  const tier = lowTier(margin, bands);
  const scaleMax = (bands?.advisory ?? 1) * DIAL_SCALE;  // dial full-scale = twice the advisory margin
  return (
    <Tile type={widget.type}>
      <p className="gauge-value">{formatValue(units, "factor", margin, lang)}</p>
      <Meter fraction={margin / scaleMax} tier={tier} label={t("widget.stability_dial.margin")} />
      <StatusBadge tier={tier} />
      {stab?.limiting_axis ? (
        <p className="muted small">{t("widget.stability_dial.limiting_axis", { axis: t(`widget.stability_dial.axis_${stab.limiting_axis}`) })}</p>
      ) : null}
      {tier !== "normal" && stab?.hint ? (
        <p className="small">{t("widget.stability_dial.hint", { hint: t(`widget.stability_dial.hint_${stab.hint}`) })}</p>
      ) : null}
    </Tile>
  );
}

// ------------------------------------------------------------------ proximity radar (top view, machine frame)
interface TrackView {
  id: string;
  x: number;
  y: number;
  distance_m: number;
  ttc_s: number | null;
  zone: string | null;
  static: boolean;
  ppe?: Record<string, boolean>;
}

export function ProximityRadar({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const { units, lang } = useUnits();
  const prox = (binding.value ?? {}) as { tracks?: TrackView[]; nearest_person_m?: number | null; min_ttc_s?: number | null; ppe_missing?: boolean };
  const zones = getPath(widget.resolved, "zones") as Record<string, number> | undefined;
  const outer = zones ? Math.max(...Object.values(zones)) : 1;
  const tracks = prox.tracks ?? [];
  const tier = prox.nearest_person_m === null || prox.nearest_person_m === undefined ? "normal" : withinTier(prox.nearest_person_m, zones);
  const ring = (tierName: string) => (zones?.[tierName] ?? 0) / outer;
  return (
    <Tile type={widget.type}>
      <div className="radar-wrap">
        <svg viewBox="-1.1 -1.1 2.2 2.2" className="radar" role="img" aria-label={t("widget.proximity_radar.title")}>
          {["advisory", "caution", "warning"].map((z) => (
            <circle key={z} r={ring(z)} className="radar-zone" data-tier={z}>
              <title>{t(`widget.proximity_radar.zone_${z}`)}</title>
            </circle>
          ))}
          <rect x={-ring("warning") * MACHINE_W * HALF} y={-ring("warning") * MACHINE_L * HALF} width={ring("warning") * MACHINE_W} height={ring("warning") * MACHINE_L} className="radar-machine" />
          {tracks.map((tr) => {
            const cx = tr.y / outer;       // machine frame: x forward (up on screen), y left (left on screen)
            const cy = -tr.x / outer;
            const inside = Math.hypot(cx, cy) <= 1;
            return inside ? (
              <circle key={tr.id} cx={-cx} cy={cy} r={0.07} className="radar-person" data-tier={tr.zone ?? "normal"} data-static={tr.static}>
                <title>{t("widget.proximity_radar.person", { id: tr.id, distance: formatValue(units, "length", tr.distance_m, lang) })}</title>
              </circle>
            ) : null;
          })}
        </svg>
        <dl className="kv small">
          <dt>{t("widget.proximity_radar.nearest")}</dt>
          <dd>{prox.nearest_person_m === null || prox.nearest_person_m === undefined ? t("widget.proximity_radar.none") : formatValue(units, "length", prox.nearest_person_m, lang)}</dd>
          {prox.min_ttc_s !== null && prox.min_ttc_s !== undefined ? (
            <>
              <dt>{t("widget.proximity_radar.ttc")}</dt>
              <dd>{formatValue(units, "seconds", prox.min_ttc_s, lang)}</dd>
            </>
          ) : null}
        </dl>
      </div>
      <StatusBadge tier={tier} />
      {prox.ppe_missing ? <p className="small">{t("widget.proximity_radar.ppe_missing")}</p> : null}
    </Tile>
  );
}

// ------------------------------------------------------------------ grade profile
export function GradeProfile({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const { units, lang } = useUnits();
  const g = (binding.value ?? {}) as { active?: boolean; deviation_m?: number; direction?: string };
  const tier: Tier = !g.active || g.direction === "on_grade" ? "normal" : "advisory";
  return (
    <Tile type={widget.type}>
      {g.active && g.deviation_m !== undefined ? (
        <>
          <p className="gauge-value">{formatValue(units, "short_length", g.deviation_m, lang)}</p>
          <p className="grade-direction" data-direction={g.direction}>{t(`widget.grade_profile.${g.direction}`)}</p>
          <StatusBadge tier={tier} />
        </>
      ) : (
        <p className="muted">{t("widget.grade_profile.inactive")}</p>
      )}
    </Tile>
  );
}

// ------------------------------------------------------------------ task progress
export function TaskProgress({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const task = (binding.value ?? {}) as {
    task_id?: string;
    progress_qty?: number;
    quantity?: number;
    unit?: string;
    cycles?: number;
    phase?: string;
    etc?: { remaining_min_p50: number; remaining_min_p10: number; remaining_min_p90: number; etc_p50: string; weight_observed: number } | null;
  };
  const f = useFormatters();
  if (!task.task_id) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t("app.empty")}</p>
      </Tile>
    );
  }
  const done = task.progress_qty ?? 0;
  const total = task.quantity ?? 0;
  return (
    <Tile type={widget.type}>
      <p className="strong">{task.task_id}</p>
      <Meter fraction={total ? done / total : 0} tier="normal" label={t("widget.task_progress.progress", { done, total })} />
      <p className="small">{t("widget.task_progress.progress", { done: `${Math.round(done)} ${task.unit ?? ""}`, total: `${total} ${task.unit ?? ""}` })}</p>
      <p className="muted small">{t("widget.task_progress.cycles", { n: task.cycles ?? 0 })}</p>
      {task.etc ? (
        <p className="small">
          <span className="strong">{t("widget.task_progress.etc", { time: f.time(task.etc.etc_p50) })}</span>
          <span className="sep" />
          {t("widget.task_progress.remaining", {
            p50: f.minutes(task.etc.remaining_min_p50),
            p10: f.minutes(task.etc.remaining_min_p10),
            p90: f.minutes(task.etc.remaining_min_p90),
          })}
        </p>
      ) : null}
    </Tile>
  );
}

// ------------------------------------------------------------------ energy
export function EnergyCard({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const { units, lang } = useUnits();
  const e = (binding.value ?? {}) as { powertrain?: string; soc?: number | null; fuel_pct?: number | null };
  const electric = e.powertrain === "electric";
  const fraction = electric ? e.soc ?? null : e.fuel_pct === null || e.fuel_pct === undefined ? null : e.fuel_pct / PCT;
  if (fraction === null || fraction === undefined) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t("app.empty")}</p>
      </Tile>
    );
  }
  return (
    <Tile type={widget.type}>
      <div className="energy-row">
        <span>{t(electric ? "widget.energy_card.soc" : "widget.energy_card.fuel")}</span>
        <strong>{formatValue(units, "ratio", fraction, lang)}</strong>
      </div>
      <Meter fraction={fraction} tier="normal" label={formatValue(units, "ratio", fraction, lang)} />
    </Tile>
  );
}

// ------------------------------------------------------------------ twin (basic 2-D side view)
export function Twin3D({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const state = useLive((s) => s.state) as Record<string, unknown>;
  const alerts = useLive((s) => s.alerts) as { alert: { severity: string } }[];
  const tier = alerts.reduce<Tier>((acc, a) => worst(acc, a.alert.severity as Tier), "normal");
  const tip = state.bucket_tip as number[] | undefined;
  if (!tip) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t("app.empty")}</p>
      </Tile>
    );
  }
  return (
    <Tile type={widget.type} tone={tier === "warning" ? "alert" : undefined}>
      <TwinView state={state} tier={tier} />
      <StatusBadge tier={tier} />
    </Tile>
  );
}

/** Schematic side view of the arm against the design grade; shared by the live twin and incident playback. */
export function TwinView({ state, tier }: { state: Record<string, unknown>; tier: Tier }) {
  const { t } = useTranslation();
  const tip = state.bucket_tip as number[] | undefined;
  const grade = state.grade as { design_z?: number } | undefined;
  const reach = Number(state.reach_m ?? 0);
  if (!tip) return null;
  const r = Math.hypot(tip[0], tip[1]);
  const view = { x0: -VIEW_BACK, x1: Math.max(VIEW_MIN_FRONT, reach + 1), z0: -VIEW_DEPTH, z1: VIEW_HEIGHT };
  const designZ = grade?.design_z;
  return (
    <svg viewBox={`${view.x0} ${-view.z1} ${view.x1 - view.x0} ${view.z1 - view.z0}`} className="twin" role="img" aria-label={t("widget.twin_3d.caption")}>
      <line x1={view.x0} x2={view.x1} y1={0} y2={0} className="twin-ground" />
      {designZ !== undefined ? (
        <line x1={view.x0} x2={view.x1} y1={-designZ} y2={-designZ} className="twin-design">
          <title>{t("widget.twin_3d.design_grade")}</title>
        </line>
      ) : null}
      <rect x={-VIEW_BACK * HALF} y={-TRACK_H} width={VIEW_BACK} height={TRACK_H} className="twin-body" />
      <polyline points={`0,${-PIVOT_Z} ${r},${-tip[2]}`} className="twin-arm" />
      <circle cx={r} cy={-tip[2]} r={TIP_R} className="twin-tip" data-tier={tier}>
        <title>{t("widget.twin_3d.tip")}</title>
      </circle>
    </svg>
  );
}

// View geometry of the schematic side view, in metres (not domain thresholds).
const VIEW_BACK = 4;
const VIEW_MIN_FRONT = 10;
const VIEW_DEPTH = 5;
const VIEW_HEIGHT = 7;
const TRACK_H = 1;
const PIVOT_Z = 1.9;
const TIP_R = 0.25;
const PCT = 100;
const HALF = 0.5;
const DIAL_SCALE = 2;
// radar machine footprint as a fraction of the warning radius
const MACHINE_W = 0.66;
const MACHINE_L = 0.5;

// ------------------------------------------------------------------ copilot banner (alert pre-emption)
interface AlertEventView {
  alert: { id: string; severity: string; message_key: string; params?: Record<string, unknown>; copilot_priority?: number };
}

export function CopilotBanner({ binding }: WidgetProps) {
  const { t } = useTranslation();
  const alerts = useLive((s) => s.alerts) as unknown as AlertEventView[];
  const adv = binding.value as { text?: string; severity?: string } | null;
  // an open caution/warning alert pre-empts the advisory and shows its template (§12.1 arbiter)
  const top = [...alerts]
    .filter((a) => a.alert.severity === "warning" || a.alert.severity === "caution")
    .sort((a, b) => SEV[b.alert.severity] - SEV[a.alert.severity] || (b.alert.copilot_priority ?? 0) - (a.alert.copilot_priority ?? 0))[0];
  const tier = (top?.alert.severity ?? adv?.severity ?? "normal") as Tier;
  const text = top ? t(top.alert.message_key, top.alert.params ?? {}) : adv?.text ?? "";
  return (
    <div className="copilot-banner" data-tier={tier === "normal" ? "none" : tier} aria-live="assertive">
      <span className="copilot-label">{t("widget.copilot_banner.title")}</span>
      {tier !== "normal" ? <StatusBadge tier={tier} /> : null}
      <span>{text}</span>
    </div>
  );
}

const SEV: Record<string, number> = { advisory: 1, caution: 2, warning: 3 };
