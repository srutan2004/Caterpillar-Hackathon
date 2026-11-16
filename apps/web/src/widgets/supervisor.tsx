// Supervisor, Fleet & Machine widgets (§14): MapView, ComplianceBoard, AnomalyBoard,
// DataTable, MaintenanceCalendar, TaskCard, VideoPlayer, SimViewport.
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useFormatters } from "../runtime/format";
import { useLive } from "../runtime/live";
import { useSelection } from "../runtime/selection";
import { Meter, StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

const ZERO = 0;
const ONE = 1;
const FIVE = 5;
const TEN = 10;
const TWENTY = 20;
const FORTY = 40;
const FIFTY = 50;
const SIXTY = 60;
const EIGHTY = 80;
const MAP_OFFSET = 50;
const MAP_SPAN = 100;
const PIN_R = 3.5;
const HEADING_LEN = 6;
const COMPLIANCE_WARN = 0.85;
const COMPLIANCE_CAUTION = 0.95;
const DEFAULT_SPEED = 0;
const DEFAULT_BOOM_DEG = 35;
const DEFAULT_STICK_DEG = -45;
const DEFAULT_BUCKET_DEG = -20;
const SVG_VIEW_SIZE = 200;
const HALF_VIEW = 100;

interface ComplianceSeatbeltData {
  overall_compliance_pct: number;
  total_active_seconds: number;
  total_unbelted_seconds: number;
  records: Array<{
    operator_id: string;
    site_id: string;
    active_seconds: number;
    unbelted_seconds: number;
    compliance_pct: number;
  }>;
}

interface CompliancePpeData {
  overall_compliance_pct: number;
  total_observations: number;
  compliant_count: number;
  observations: Array<{
    id: string;
    operator_id: string;
    vest_ok: boolean;
    hard_hat_ok: boolean;
    ts: string;
  }>;
}

interface AnomalyItem {
  id: string;
  machine_id: string;
  type: string;
  severity: Tier;
  description: string;
  timestamp: string;
  score: number;
}

interface MaintenanceWindowItem {
  machine_id: string;
  component: string;
  window_start: string;
  window_end: string;
  duration_h: number;
  technician_id?: string;
  tier?: Tier;
}

interface TaskData {
  id?: string;
  task_id?: string;
  type?: string;
  status?: string;
  planned_start?: string;
  planned_end?: string;
  quantity?: number;
  progress_qty?: number;
  unit?: string;
  deadline?: string | null;
  etc?: { remaining_min_p50: number; remaining_min_p10: number; remaining_min_p90: number };
  best_start?: { recommended_start: string; minutes_saved_vs_usual: number };
  energy?: { can_finish: boolean };
}

// ------------------------------------------------------------------ 1. MapView
export function MapView({ widget, binding, props }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const show = (props.show as string[] | undefined) ?? ["haul_road", "geofences", "machines"];
  const liveState = (useLive((s) => s.state) ?? {}) as Record<string, unknown>;
  const motion = (liveState.motion ?? {}) as { ground_speed_kph?: number; heading_deg?: number };
  const machinePos = (liveState.gps ?? { x: ZERO, y: ZERO }) as { x: number; y: number };
  const speed = motion.ground_speed_kph ?? DEFAULT_SPEED;
  const heading = motion.heading_deg ?? ZERO;

  const showRoad = show.includes("haul_road");
  const showFences = show.includes("geofences");
  const showMachines = show.includes("machines");

  return (
    <Tile type={widget.type}>
      <div className="map-container">
        <svg
          viewBox={`${-MAP_OFFSET} ${-MAP_OFFSET} ${MAP_SPAN} ${MAP_SPAN}`}
          className="map-svg"
          role="img"
          aria-label={t("widget.map_view.title")}
        >
          {/* Site boundary / grid */}
          <rect
            x={-MAP_OFFSET + ONE}
            y={-MAP_OFFSET + ONE}
            width={MAP_SPAN - ONE - ONE}
            height={MAP_SPAN - ONE - ONE}
            className="map-boundary"
          />

          {/* Haul road */}
          {showRoad ? (
            <path
              d="M -35 -25 C -10 -20, 10 15, 35 30"
              className="map-haul-road"
            />
          ) : null}

          {/* Geofences */}
          {showFences ? (
            <>
              {/* Loading zone */}
              <rect x={-42} y={-38} width={22} height={TWENTY} className="map-zone" data-zone="loading" />
              <text x={-31} y={-26} className="map-label">
                {t("widget.map_view.loading_zone")}
              </text>

              {/* Dump zone */}
              <rect x={24} y={18} width={22} height={22} className="map-zone" data-zone="dump" />
              <text x={35} y={31} className="map-label">
                {t("widget.map_view.dump_zone")}
              </text>

              {/* Charging station */}
              <rect x={-FORTY} y={15} width={18} height={16} className="map-zone" data-zone="charge" />
              <text x={-31} y={25} className="map-label">
                {t("widget.map_view.charging_station")}
              </text>
            </>
          ) : null}

          {/* Machine pin */}
          {showMachines ? (
            <g transform={`translate(${machinePos.x}, ${machinePos.y})`}>
              <circle r={PIN_R} className="map-pin" />
              <line
                x1={ZERO}
                y1={ZERO}
                x2={Math.sin((heading * Math.PI) / EIGHTY) * HEADING_LEN}
                y2={-Math.cos((heading * Math.PI) / EIGHTY) * HEADING_LEN}
                className="map-heading-pointer"
              />
            </g>
          ) : null}
        </svg>

        <div className="map-stats small">
          <span>{t("widget.map_view.speed", { kph: f.num(speed, ONE) })}</span>
          <span className="sep" />
          <span>{binding.status}</span>
        </div>
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------ 2. ComplianceBoard
export function ComplianceBoard({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const siteId = useSelection((s) => s.siteId);

  const seatbeltQ = useQuery({
    queryKey: ["compliance", "seatbelt", siteId],
    queryFn: () => api<ComplianceSeatbeltData>(`/api/compliance/seatbelt${siteId ? `?site_id=${encodeURIComponent(siteId)}` : ""}`),
  });

  const ppeQ = useQuery({
    queryKey: ["compliance", "ppe", siteId],
    queryFn: () => api<CompliancePpeData>(`/api/compliance/ppe${siteId ? `?site_id=${encodeURIComponent(siteId)}` : ""}`),
  });

  const seatRate = seatbeltQ.data?.overall_compliance_pct ?? ONE;
  const ppeRate = ppeQ.data?.overall_compliance_pct ?? ONE;

  const seatTier: Tier = seatRate >= COMPLIANCE_CAUTION ? "normal" : seatRate >= COMPLIANCE_WARN ? "caution" : "warning";
  const ppeTier: Tier = ppeRate >= COMPLIANCE_CAUTION ? "normal" : ppeRate >= COMPLIANCE_WARN ? "caution" : "warning";

  return (
    <Tile type={widget.type}>
      <div className="compliance-row">
        <div className="compliance-card">
          <div className="compliance-header">
            <span className="strong small">{t("widget.compliance_board.seatbelt")}</span>
            <StatusBadge tier={seatTier} />
          </div>
          <p className="gauge-value">{f.pct(seatRate)}</p>
          <Meter fraction={seatRate} tier={seatTier} label={t("widget.compliance_board.seatbelt")} />
          <p className="small muted">
            {seatbeltQ.data?.total_unbelted_seconds
              ? t("widget.compliance_board.unbuckled_time", { minutes: f.minutes(seatbeltQ.data.total_unbelted_seconds / SIXTY) })
              : t("widget.compliance_board.all_compliant")}
          </p>
        </div>

        <div className="compliance-card">
          <div className="compliance-header">
            <span className="strong small">{t("widget.compliance_board.ppe")}</span>
            <StatusBadge tier={ppeTier} />
          </div>
          <p className="gauge-value">{f.pct(ppeRate)}</p>
          <Meter fraction={ppeRate} tier={ppeTier} label={t("widget.compliance_board.ppe")} />
          <p className="small muted">
            {ppeQ.data?.compliant_count !== undefined
              ? t("widget.compliance_board.violations", { n: (ppeQ.data.total_observations - ppeQ.data.compliant_count) })
              : t("widget.compliance_board.all_compliant")}
          </p>
        </div>
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------ 3. AnomalyBoard
export function AnomalyBoard({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const boundData = binding.value as { anomalies?: AnomalyItem[] } | AnomalyItem[] | undefined;
  const anomalies: AnomalyItem[] = Array.isArray(boundData)
    ? boundData
    : boundData?.anomalies ?? [];

  return (
    <Tile type={widget.type}>
      {anomalies.length === ZERO ? (
        <p className="muted small">{t("widget.anomaly_board.empty")}</p>
      ) : (
        <ul className="service-list">
          {anomalies.map((a) => (
            <li key={a.id}>
              <StatusBadge tier={a.severity || "advisory"} />
              <span className="strong">{a.machine_id}</span>
              <span>{a.description || a.type}</span>
              <span className="small muted">{t("widget.anomaly_board.score", { score: f.num(a.score, ONE) })}</span>
              {a.timestamp ? <span className="small muted">{f.time(a.timestamp)}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </Tile>
  );
}

// ------------------------------------------------------------------ 4. DataTable
export function DataTable({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const raw = binding.value;

  if (!raw) {
    return (
      <Tile type={widget.type}>
        <p className="muted small">{t("widget.data_table.empty")}</p>
      </Tile>
    );
  }

  // Handle config validation result object: { valid, errors, warnings, checks }
  if (typeof raw === "object" && raw !== null && ("valid" in raw || "checks" in raw)) {
    const valObj = raw as {
      valid?: boolean;
      errors?: string[];
      warnings?: string[];
      checks?: Array<{ name: string; status: string; message: string }>;
    };
    const checks = valObj.checks ?? [
      ...(valObj.errors ?? []).map((e) => ({ name: "Error", status: "error", message: e })),
      ...(valObj.warnings ?? []).map((w) => ({ name: "Warning", status: "warn", message: w })),
    ];

    return (
      <Tile type={widget.type}>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("widget.data_table.column_name")}</th>
              <th>{t("widget.data_table.column_status")}</th>
              <th>{t("widget.data_table.column_detail")}</th>
            </tr>
          </thead>
          <tbody>
            {checks.length === ZERO ? (
              <tr>
                <td colSpan={3} className="muted small">
                  {t("widget.compliance_board.all_ok")}
                </td>
              </tr>
            ) : (
              checks.map((c, i) => (
                <tr key={i}>
                  <td className="strong">{c.name}</td>
                  <td>
                    <StatusBadge tier={c.status === "ok" ? "normal" : c.status === "warn" ? "caution" : "warning"} />
                  </td>
                  <td className="small">{c.message}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Tile>
    );
  }

  // Handle generic array of objects
  if (Array.isArray(raw)) {
    if (raw.length === ZERO) {
      return (
        <Tile type={widget.type}>
          <p className="muted small">{t("widget.data_table.empty")}</p>
        </Tile>
      );
    }
    const cols = Object.keys(raw[ZERO] as Record<string, unknown>).slice(ZERO, FIVE);
    return (
      <Tile type={widget.type}>
        <table className="data-table">
          <thead>
            <tr>
              {cols.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {raw.slice(ZERO, TEN).map((row, idx) => (
              <tr key={idx}>
                {cols.map((col) => (
                  <td key={col} className="small">
                    {String((row as Record<string, unknown>)[col] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Tile>
    );
  }

  return (
    <Tile type={widget.type}>
      <p className="muted small">{t("widget.data_table.empty")}</p>
    </Tile>
  );
}

// ------------------------------------------------------------------ 5. MaintenanceCalendar
export function MaintenanceCalendar({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const machineId = useSelection((s) => s.machineId);

  const q = useQuery({
    queryKey: ["maintenance-windows", machineId],
    queryFn: () =>
      api<MaintenanceWindowItem[]>(
        `/api/maintenance/windows${machineId ? `?machine=${encodeURIComponent(machineId)}` : ""}`
      ),
  });

  const windows = q.data ?? [];

  return (
    <Tile type={widget.type}>
      {windows.length === ZERO ? (
        <p className="muted small">{t("widget.maintenance_calendar.empty")}</p>
      ) : (
        <ul className="service-list">
          {windows.map((w, idx) => (
            <li key={idx}>
              <StatusBadge tier={w.tier ?? "normal"} />
              <span className="strong">{w.machine_id}</span>
              <span>{t(`maintenance.component.${w.component}`, { defaultValue: w.component })}</span>
              <span className="small muted">
                {t("widget.maintenance_calendar.duration", { h: f.num(w.duration_h, ONE) })}
              </span>
              <span className="small muted">
                {t("widget.maintenance_calendar.window", {
                  start: f.time(w.window_start),
                  end: f.time(w.window_end),
                })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Tile>
  );
}

// ------------------------------------------------------------------ 6. TaskCard
export function TaskCard({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const task = (binding.value ?? {}) as TaskData;
  const taskId = task.id || task.task_id;

  if (!taskId) {
    return (
      <Tile type={widget.type}>
        <p className="muted small">{t("widget.task_card.empty")}</p>
      </Tile>
    );
  }

  const done = task.progress_qty ?? ZERO;
  const total = task.quantity ?? ONE;
  const fraction = total > ZERO ? done / total : ZERO;

  return (
    <Tile type={widget.type}>
      <div className="task-card-standalone">
        <div className="task-header-row">
          <span className="strong">{task.type ? t(`task.type.${task.type}`) : taskId}</span>
          <span className="chip">{task.status ? t(`task.status.${task.status}`) : ""}</span>
        </div>

        {task.planned_start && task.planned_end ? (
          <p className="small muted">
            {t("widget.task_timeline.window", {
              start: f.time(task.planned_start),
              end: f.time(task.planned_end),
            })}
          </p>
        ) : null}

        <Meter fraction={fraction} tier="normal" label={f.pct(fraction)} />

        <p className="small">
          {t("widget.task_progress.progress", {
            done: f.num(done, ZERO),
            total: f.num(total, ZERO),
          })}
        </p>

        {task.etc ? (
          <p className="small strong">
            {t("widget.task_progress.remaining", {
              p50: f.minutes(task.etc.remaining_min_p50),
              p10: f.minutes(task.etc.remaining_min_p10),
              p90: f.minutes(task.etc.remaining_min_p90),
            })}
          </p>
        ) : null}
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------ 7. VideoPlayer
export function VideoPlayer({ widget, props }: WidgetProps) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const src = (props.src as string | undefined) ?? "";
  const chapters = (props.chapters as Array<{ title_key: string; start_s: number }> | undefined) ?? [];

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (playing) {
      videoRef.current.pause();
      setPlaying(false);
    } else {
      videoRef.current.play().catch(() => {});
      setPlaying(true);
    }
  };

  const jumpTo = (timeS: number) => {
    if (!videoRef.current) return;
    videoRef.current.currentTime = timeS;
    videoRef.current.play().catch(() => {});
    setPlaying(true);
  };

  return (
    <Tile type={widget.type}>
      <div className="video-player-widget">
        {src ? (
          <video
            ref={videoRef}
            src={src}
            className="video-element"
            controls
            aria-label={t("widget.video_player.title")}
          />
        ) : (
          <div className="video-placeholder">
            <p className="muted small">{t("widget.video_player.empty")}</p>
          </div>
        )}

        <div className="video-controls">
          <button type="button" className="primary" onClick={togglePlay}>
            {t(playing ? "widget.video_player.pause" : "widget.video_player.play")}
          </button>
        </div>

        {chapters.length > ZERO ? (
          <div className="video-chapters">
            <span className="strong small">{t("widget.video_player.chapters")}</span>
            <ul className="chapter-list">
              {chapters.map((c, i) => (
                <li key={i}>
                  <button type="button" className="ghost small" onClick={() => jumpTo(c.start_s)}>
                    {t(c.title_key)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------ 8. SimViewport
export function SimViewport({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const state = (useLive((s) => s.state) ?? {}) as Record<string, unknown>;

  const boomDeg = (state.boom_angle_deg as number | undefined) ?? DEFAULT_BOOM_DEG;
  const stickDeg = (state.stick_angle_deg as number | undefined) ?? DEFAULT_STICK_DEG;
  const bucketDeg = (state.bucket_angle_deg as number | undefined) ?? DEFAULT_BUCKET_DEG;
  const payload = (state.payload_t as number | undefined) ?? ZERO;

  return (
    <Tile type={widget.type}>
      <div className="sim-viewport-container">
        <svg
          viewBox={`0 0 ${SVG_VIEW_SIZE} ${SVG_VIEW_SIZE}`}
          className="sim-viewport-svg"
          role="img"
          aria-label={t("widget.sim_viewport.title")}
        >
          {/* Ground surface */}
          <line x1={ZERO} y1={HALF_VIEW + FORTY} x2={SVG_VIEW_SIZE} y2={HALF_VIEW + FORTY} className="twin-ground" />

          {/* Machine chassis base */}
          <rect x={TWENTY} y={HALF_VIEW + TWENTY} width={FORTY} height={TWENTY} className="twin-body" />
          <circle cx={FORTY} cy={HALF_VIEW + TWENTY} r={FIVE} className="twin-body" />

          {/* Excavator arm links: Boom, Stick, Bucket */}
          <g transform={`translate(${FORTY}, ${HALF_VIEW + TWENTY}) rotate(${-boomDeg})`}>
            <line x1={ZERO} y1={ZERO} x2={FIFTY} y2={ZERO} className="twin-arm" />
            <g transform={`translate(${FIFTY}, 0) rotate(${-stickDeg})`}>
              <line x1={ZERO} y1={ZERO} x2={FORTY} y2={ZERO} className="twin-arm" />
              <g transform={`translate(${FORTY}, 0) rotate(${-bucketDeg})`}>
                <polygon points="0,0 20,10 15,20 0,0" className="twin-tip" />
              </g>
            </g>
          </g>
        </svg>

        <div className="sim-telemetry small">
          <span>
            {t("widget.sim_viewport.arm_angles", {
              boom: f.num(boomDeg, ZERO),
              stick: f.num(stickDeg, ZERO),
              bucket: f.num(bucketDeg, ZERO),
            })}
          </span>
          <span className="sep" />
          <span>{t("widget.sim_viewport.payload", { t: f.num(payload, ONE) })}</span>
        </div>
      </div>
    </Tile>
  );
}
