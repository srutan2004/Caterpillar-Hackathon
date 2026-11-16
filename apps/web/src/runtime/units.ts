// formatValue is the ONLY value formatter (§14). Values travel in SI; display units come from bootstrap.
export interface UnitQuantity {
  unit: string;
  symbol: string;
  factor: number;
  precision: number;
  offset?: number;
}

export interface UnitsConfig {
  system: string;
  quantities: Record<string, UnitQuantity>;
}

export function convert(q: UnitQuantity, si: number): number {
  return si * q.factor + (q.offset ?? 0);
}

export function formatValue(units: UnitsConfig, quantity: string, si: number | null | undefined, locale: string): string {
  const q = units.quantities[quantity];
  if (si === null || si === undefined || Number.isNaN(si)) return "—";
  if (!q) return String(si);
  const value = convert(q, si);
  const text = new Intl.NumberFormat(locale, { maximumFractionDigits: q.precision, minimumFractionDigits: q.precision }).format(value);
  return `${text} ${q.symbol}`;
}
