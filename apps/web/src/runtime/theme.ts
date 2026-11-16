// Theme adapter (§14): design tokens from config/theme.yaml → CSS custom properties.
// This is the only module allowed to touch raw token values; components use var(--…) only.

type TokenTree = { [key: string]: string | number | TokenTree };

export interface ThemeConfig {
  default_variant: string;
  variants: Record<string, TokenTree>;
  device_theme: Record<string, string>;
  [group: string]: unknown;
}

const VARIANT_GROUPS = new Set(["variants", "default_variant", "device_theme", "alert_behaviour"]);

export function flattenTokens(tree: TokenTree, prefix: string, out: Record<string, string>): Record<string, string> {
  for (const [key, value] of Object.entries(tree)) {
    const name = `${prefix}-${key}`.replace(/_/g, "-");
    if (typeof value === "object") flattenTokens(value, name, out);
    else out[name] = String(value);
  }
  return out;
}

export function themeVariables(theme: ThemeConfig, device: string): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const [group, value] of Object.entries(theme)) {
    if (VARIANT_GROUPS.has(group) || typeof value !== "object" || value === null) continue;
    flattenTokens(value as TokenTree, `--${group}`, vars);
  }
  const variant = theme.device_theme[device] ?? theme.default_variant;
  flattenTokens(theme.variants[variant] ?? {}, "-", vars);
  return Object.fromEntries(Object.entries(vars).map(([k, v]) => [k.replace(/^---/, "--"), v]));
}

export function applyTheme(theme: ThemeConfig, device: string): void {
  const root = document.documentElement;
  for (const [name, value] of Object.entries(themeVariables(theme, device))) root.style.setProperty(name, value);
  root.dataset.device = device;
}
