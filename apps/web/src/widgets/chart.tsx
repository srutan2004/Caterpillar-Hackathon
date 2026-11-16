// Minimal SVG line chart for planning/maintenance widgets. Dataviz rules: thin 2px lines, one y-axis,
// recessive grid, text in text tokens (never series colours), a legend whenever there are two or more series,
// and a hover crosshair + tooltip. Colours are chart tokens from config/theme.yaml.
import { useRef, useState, type MouseEvent, type ReactNode } from "react";

export interface XY {
  x: number;
  y: number;
}

export interface Series {
  id: string;
  label: string;
  role: "series_1" | "series_2" | "reference";
  points: XY[];
  dashed?: boolean;
}

export interface Band {
  label: string;
  points: { x: number; lo: number; hi: number }[];
}

export interface Rule {
  y: number;
  label: string;
  tier: string;
}

export interface Marker {
  x: number;
  label: string;
  kind: string;
}

export interface Region {
  x0: number;
  x1: number;
  label: string;
}

interface Props {
  series: Series[];
  band?: Band;
  rules?: Rule[];
  markers?: Marker[];
  regions?: Region[];
  formatX: (x: number) => string;
  formatY: (y: number) => string;
  yLabel: string;
  ariaLabel: string;
  yDomain?: [number, number];
  footer?: ReactNode;
}

const W = 100;
const H = 50;
const PAD_L = 1;
const PAD_R = 1;
const PAD_T = 3;
const PAD_B = 3;
const TICKS = 4;
const PAD_FRACTION = 0.08;
const HUNDRED = 100;

function extent(values: number[]): [number, number] {
  const finite = values.filter((v) => Number.isFinite(v));
  if (!finite.length) return [0, 1];
  const lo = Math.min(...finite);
  const hi = Math.max(...finite);
  if (lo === hi) return [lo - 1, hi + 1];
  const pad = (hi - lo) * PAD_FRACTION;
  return [lo - pad, hi + pad];
}

function nearestIndex(xs: number[], x: number): number {
  let best = 0;
  xs.forEach((v, i) => {
    if (Math.abs(v - x) < Math.abs(xs[best] - x)) best = i;
  });
  return best;
}

export function LineChart({ series, band, rules = [], markers = [], regions = [], formatX, formatY, yLabel, ariaLabel, yDomain, footer }: Props) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const xs = [...series.flatMap((s) => s.points.map((p) => p.x)), ...(band?.points.map((p) => p.x) ?? []), ...markers.map((m) => m.x)];
  const ys = [...series.flatMap((s) => s.points.map((p) => p.y)), ...(band?.points.flatMap((p) => [p.lo, p.hi]) ?? []), ...rules.map((r) => r.y)];
  const x0 = xs.length ? Math.min(...xs) : 0;
  const x1 = xs.length ? Math.max(...xs) : 1;
  const [y0, y1] = yDomain ?? extent(ys);
  const sx = (x: number) => PAD_L + ((x - x0) / (x1 - x0 || 1)) * (W - PAD_L - PAD_R);
  const sy = (y: number) => H - PAD_B - ((y - y0) / (y1 - y0 || 1)) * (H - PAD_T - PAD_B);
  const path = (pts: XY[]) => pts.map((p, i) => `${i ? "L" : "M"}${sx(p.x)},${sy(p.y)}`).join(" ");
  const bandPath = band?.points.length
    ? `${band.points.map((p, i) => `${i ? "L" : "M"}${sx(p.x)},${sy(p.hi)}`).join(" ")} ${[...band.points]
        .reverse()
        .map((p) => `L${sx(p.x)},${sy(p.lo)}`)
        .join(" ")} Z`
    : null;
  const yticks = Array.from({ length: TICKS + 1 }, (_, i) => y0 + ((y1 - y0) * i) / TICKS);
  const xticks = Array.from({ length: TICKS + 1 }, (_, i) => x0 + ((x1 - x0) * i) / TICKS);

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || !box.width) return;
    const vx = ((e.clientX - box.left) / box.width) * W;
    setHover(Math.max(x0, Math.min(x1, x0 + ((vx - PAD_L) / (W - PAD_L - PAD_R)) * (x1 - x0))));
  };
  const rows =
    hover === null
      ? []
      : series.filter((s) => s.points.length).map((s) => ({ s, p: s.points[nearestIndex(s.points.map((q) => q.x), hover)] }));
  const bandAt = hover !== null && band?.points.length ? band.points[nearestIndex(band.points.map((q) => q.x), hover)] : null;
  const pct = (v: number, of: number) => `${(v / of) * HUNDRED}%`;

  return (
    <figure className="chart">
      {series.length > 1 || band ? (
        <figcaption className="chart-legend">
          {series.map((s) => (
            <span key={s.id} className="legend-item" data-role={s.role} data-dashed={s.dashed ? "true" : undefined}>
              <span className="legend-swatch" aria-hidden="true" />
              {s.label}
            </span>
          ))}
          {band ? (
            <span className="legend-item" data-role="band">
              <span className="legend-swatch" aria-hidden="true" />
              {band.label}
            </span>
          ) : null}
        </figcaption>
      ) : null}
      <div className="chart-body">
        <div className="chart-axis-y" aria-hidden="true">
          {[...yticks].reverse().map((y) => (
            <span key={`y${y}`}>{formatY(y)}</span>
          ))}
        </div>
        <div className="chart-frame">
          <svg
            ref={ref}
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            className="chart-svg"
            role="img"
            aria-label={ariaLabel}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          >
            {yticks.map((y) => (
              <line key={`g${y}`} className="chart-grid" x1={PAD_L} x2={W - PAD_R} y1={sy(y)} y2={sy(y)} />
            ))}
            {regions.map((r) => (
              <rect key={`r${r.x0}`} className="chart-region" x={sx(r.x0)} width={Math.max(sx(r.x1) - sx(r.x0), 0)} y={PAD_T} height={H - PAD_T - PAD_B}>
                <title>{r.label}</title>
              </rect>
            ))}
            {bandPath ? <path className="chart-band" d={bandPath} /> : null}
            {rules.map((r) => (
              <line key={`t${r.tier}`} className="chart-rule" data-tier={r.tier} x1={PAD_L} x2={W - PAD_R} y1={sy(r.y)} y2={sy(r.y)} />
            ))}
            {series.map((s) => (
              <path key={s.id} className="chart-line" data-role={s.role} data-dashed={s.dashed ? "true" : undefined} d={path(s.points)} />
            ))}
            {markers.map((m) => (
              <line key={`m${m.kind}`} className="chart-marker" data-kind={m.kind} x1={sx(m.x)} x2={sx(m.x)} y1={PAD_T} y2={H - PAD_B} />
            ))}
            {hover !== null ? <line className="chart-crosshair" x1={sx(hover)} x2={sx(hover)} y1={PAD_T} y2={H - PAD_B} /> : null}
          </svg>
          {markers.map((m) => (
            <span key={`ml${m.kind}`} className="chart-marker-label" data-kind={m.kind} style={{ left: pct(sx(m.x), W) }}>
              {m.label}
            </span>
          ))}
          {rules.map((r) => (
            <span key={`rl${r.tier}`} className="chart-rule-label" data-tier={r.tier} style={{ top: pct(sy(r.y), H) }}>
              {r.label}
            </span>
          ))}
          {hover !== null && rows.length ? (
            <div className="chart-tooltip" style={{ left: pct(sx(hover), W) }} role="status">
              <strong>{formatX(rows[0].p.x)}</strong>
              {rows.map(({ s, p }) => (
                <span key={s.id}>
                  {s.label}
                  <span className="sep" />
                  {formatY(p.y)}
                </span>
              ))}
              {bandAt ? (
                <span>
                  {band?.label}
                  <span className="sep" />
                  {formatY(bandAt.lo)}
                  <span className="dash" />
                  {formatY(bandAt.hi)}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <span />
        <div className="chart-axis-x" aria-hidden="true">
          {xticks.map((x) => (
            <span key={`x${x}`}>{formatX(x)}</span>
          ))}
        </div>
      </div>
      <p className="muted small">{yLabel}</p>
      {footer}
    </figure>
  );
}
