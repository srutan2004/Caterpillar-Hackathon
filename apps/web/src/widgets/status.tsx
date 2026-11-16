// Status helpers shared by cockpit widgets. Tier colours come from theme tokens; every tier also carries a
// shape and a text label so state never relies on colour alone.
import { useTranslation } from "react-i18next";

export type Tier = "normal" | "advisory" | "caution" | "warning";

const ORDER: Tier[] = ["normal", "advisory", "caution", "warning"];

/** Value inside manifest bands ({normal:[lo,hi], caution:[..], warning:[..]}). */
export function bandTier(value: number, bands: Record<string, [number, number]> | undefined): Tier {
  if (!bands) return "normal";
  const hit = ORDER.filter((tier) => {
    const b = bands[tier];
    return b && value >= b[0] && value < b[1];
  });
  return hit[hit.length - 1] ?? "normal";
}

/** Lower-is-worse thresholds ({advisory, caution, warning}), e.g. stability margin. */
export function lowTier(value: number, thresholds: Record<string, number> | undefined): Tier {
  if (!thresholds) return "normal";
  return ([...ORDER].reverse().find((tier) => tier !== "normal" && thresholds[tier] !== undefined && value < thresholds[tier]) ??
    "normal") as Tier;
}

/** Higher-is-worse thresholds evaluated as "closer than" (e.g. proximity zones in metres). */
export function withinTier(distance: number, zones: Record<string, number> | undefined): Tier {
  if (!zones) return "normal";
  return ([...ORDER].reverse().find((tier) => tier !== "normal" && zones[tier] !== undefined && distance < zones[tier]) ??
    "normal") as Tier;
}

export function worst(a: Tier, b: Tier): Tier {
  return ORDER.indexOf(a) >= ORDER.indexOf(b) ? a : b;
}

const SHAPES: Record<Tier, string> = {
  normal: "M6 1 A5 5 0 1 1 5.99 1 Z",
  advisory: "M6 1 A5 5 0 1 1 5.99 1 Z M5 4 H7 V9 H5 Z",
  caution: "M6 1 L11 6 L6 11 L1 6 Z",
  warning: "M6 1 L11 11 H1 Z",
};

export function StatusBadge({ tier }: { tier: Tier }) {
  const { t } = useTranslation();
  return (
    <span className="status-badge" data-tier={tier}>
      <svg viewBox="0 0 12 12" className="status-icon" aria-hidden="true">
        <path d={SHAPES[tier]} fillRule="evenodd" />
      </svg>
      {t(`alert.tier.${tier}`)}
    </span>
  );
}

/** Horizontal meter: the fill carries severity; the track is the neutral raised surface. */
export function Meter({ fraction, tier, label }: { fraction: number; tier: Tier; label: string }) {
  const f = Math.max(0, Math.min(1, fraction));
  return (
    <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={f} aria-label={label} title={label}>
      <div className="meter-fill" data-tier={tier} style={{ width: `${f * PCT}%` }} />
    </div>
  );
}

const PCT = 100;
