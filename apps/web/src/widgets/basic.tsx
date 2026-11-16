// Widgets implemented in Phase 1 (shell). Live cockpit widgets render real data once Phase 2 publishes it.
import { useTranslation } from "react-i18next";

import { useBootstrap } from "../app/bootstrap";
import { getPath } from "../runtime/live";
import { formatValue, type UnitsConfig } from "../runtime/units";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

export function AppBrand({ binding }: WidgetProps) {
  const { t } = useTranslation();
  const product = (binding.value ?? {}) as { name?: string; tagline_key?: string };
  return (
    <div className="brand">
      <h1 className="brand-name">{product.name}</h1>
      {product.tagline_key ? <p className="brand-tagline">{t(product.tagline_key)}</p> : null}
    </div>
  );
}

export function ScreenHeader({ props }: WidgetProps) {
  const { t } = useTranslation();
  return (
    <header className="screen-header">
      <h1>{t(String(props.title_key))}</h1>
      {props.subtitle_key ? <p className="muted">{t(String(props.subtitle_key))}</p> : null}
    </header>
  );
}

export function PendingWidget({ widget, props }: WidgetProps) {
  const { t } = useTranslation();
  return (
    <Tile type={widget.type} titleKey={props.title_key as string | undefined} tone="pending">
      <p className="muted">{t("app.widget_pending")}</p>
    </Tile>
  );
}

export function UnknownWidget({ widget }: WidgetProps) {
  const { t } = useTranslation();
  if (!import.meta.env.DEV) return null;
  return (
    <Tile type={widget.type} tone="error">
      <p>{t("app.unknown_widget", { type: widget.type })}</p>
    </Tile>
  );
}

interface AlertEvent {
  alert: { id: string; severity: string; message_key: string; params?: Record<string, unknown> };
}

export function AlertStack({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const max = Number(getPath(widget.resolved, "max_visible") ?? 0);
  const alerts = ((binding.value as AlertEvent[] | undefined) ?? []).slice(-max || undefined).reverse();
  return (
    <Tile type={widget.type}>
      {alerts.length === 0 ? (
        <p className="muted">{t("widget.alert_stack.none")}</p>
      ) : (
        <ul className="alert-list">
          {alerts.map((a) => (
            <li key={a.alert.id} className="alert" data-tier={a.alert.severity}>
              <strong>{t(`alert.tier.${a.alert.severity}`)}</strong> {t(a.alert.message_key, a.alert.params ?? {})}
            </li>
          ))}
        </ul>
      )}
    </Tile>
  );
}



interface LlmStatus {
  profile: string;
  groq_key_configured: boolean;
  tasks: Record<string, { calls: number; fallback_rate: number; p95_ms: number | null }>;
}

export function LlmStatusTile({ widget, binding }: WidgetProps) {
  const { t, i18n } = useTranslation();
  const boot = useBootstrap();
  const s = binding.value as LlmStatus | undefined;
  if (!s || !boot) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(binding.status === "error" ? "error.forbidden" : "app.loading")}</p>
      </Tile>
    );
  }
  const units = boot.units as unknown as UnitsConfig;
  return (
    <Tile type={widget.type}>
      <dl className="kv">
        <dt>{t("widget.llm_status_tile.profile")}</dt>
        <dd>{t(`widget.llm_status_tile.profile_${s.profile}`)}</dd>
        <dt>{t("widget.llm_status_tile.key")}</dt>
        <dd>{t(s.groq_key_configured ? "widget.llm_status_tile.yes" : "widget.llm_status_tile.no")}</dd>
      </dl>
      {Object.keys(s.tasks).length === 0 ? (
        <p className="muted">{t("widget.llm_status_tile.no_calls")}</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("widget.llm_status_tile.task")}</th>
              <th>{t("widget.llm_status_tile.calls")}</th>
              <th>{t("widget.llm_status_tile.fallback_rate")}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(s.tasks).map(([task, v]) => (
              <tr key={task}>
                <td>{task}</td>
                <td>{v.calls}</td>
                <td>{formatValue(units, "ratio", v.fallback_rate, i18n.language)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Tile>
  );
}
