// Display formatting for API values. Durations travel in minutes from planning endpoints and are converted to
// SI seconds for formatValue (the only unit formatter); times are shown in the site timezone from bootstrap.
import { useTranslation } from "react-i18next";

import { useBootstrap } from "../app/bootstrap";
import { formatValue, type UnitsConfig } from "./units";

export const SECONDS_PER_MINUTE = 60;
export const PERCENT = 100;

export interface Formatters {
  minutes: (m: number | null | undefined) => string;
  time: (iso: string | null | undefined) => string;
  day: (iso: string | null | undefined) => string;
  pct: (fraction: number | null | undefined) => string;
  num: (v: number | null | undefined, digits?: number) => string;
  money: (v: number | null | undefined) => string;
  lang: string;
  tz: string;
}

export function useFormatters(): Formatters {
  const boot = useBootstrap();
  const { i18n } = useTranslation();
  const lang = i18n.language;
  const tz = (boot?.timezone as string | undefined) ?? "UTC";
  const units = (boot?.units ?? { system: "", quantities: {} }) as unknown as UnitsConfig;
  const timeFmt = new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit", timeZone: tz });
  const dayFmt = new Intl.DateTimeFormat(lang, { weekday: "short", day: "numeric", month: "short", timeZone: tz });
  return {
    minutes: (m) => (m === null || m === undefined ? "—" : formatValue(units, "duration", m * SECONDS_PER_MINUTE, lang)),
    time: (iso) => (iso ? timeFmt.format(new Date(iso)) : "—"),
    day: (iso) => (iso ? dayFmt.format(new Date(iso)) : "—"),
    pct: (f) => (f === null || f === undefined ? "—" : formatValue(units, "ratio", f, lang)),
    num: (v, digits = 1) =>
      v === null || v === undefined ? "—" : new Intl.NumberFormat(lang, { maximumFractionDigits: digits }).format(v),
    money: (v) => (v === null || v === undefined ? "—" : formatValue(units, "currency", v, lang)),
    lang,
    tz,
  };
}
