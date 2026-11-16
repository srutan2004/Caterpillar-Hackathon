// Layout engine (§14): fetches the layout for (screen, device, manifest) and places widgets on a CSS grid.
// Placement numbers come from YAML; spacing comes from theme tokens. Widgets never contain numbers.
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api, type LayoutOut, type ResolvedWidget } from "../api/client";
import { useBinding } from "./binding";
import { resolveWidget } from "./registry";
import type { WidgetContext } from "../widgets/types";

function tokenVar(token: string): string {
  return `var(--${token.replace(/\./g, "-").replace(/_/g, "-")})`;
}

function WidgetSlot({ widget, ctx }: { widget: ResolvedWidget; ctx: WidgetContext }) {
  const { t } = useTranslation();
  const def = resolveWidget(widget.type);
  const binding = useBinding(widget.bind);
  const parsed = def.props.safeParse(widget.props ?? {});
  const [col, row, colSpan, rowSpan] = widget.area;
  const style = { gridColumn: `${col} / span ${colSpan}`, gridRow: `${row} / span ${rowSpan}` };
  const Component = def.component;
  return (
    <div className="slot" style={style} data-widget-id={widget.id}>
      {parsed.success ? (
        <Component widget={widget} binding={binding} props={parsed.data as Record<string, unknown>} ctx={ctx} />
      ) : (
        <p className="form-error">{t("app.unknown_widget", { type: widget.type })}</p>
      )}
    </div>
  );
}

interface Props {
  screen: string;
  device: string;
  manifestId?: string;
  machineId?: string;
  mode?: string;
}

export function LayoutRenderer({ screen, device, manifestId, machineId, mode = "normal" }: Props) {
  const { t } = useTranslation();
  const params = new URLSearchParams({ screen, device });
  if (manifestId) params.set("manifest_id", manifestId);
  const layout = useQuery({
    queryKey: ["layout", screen, device, manifestId],
    queryFn: () => api<LayoutOut>(`/api/ui/layout?${params.toString()}`),
  });
  if (!layout.data) return <p className="muted">{t(layout.isError ? "error.not_found" : "app.loading")}</p>;
  const l = layout.data;
  const grid = l.grid as { columns: number; rows: number; gap_token: string };
  const hidden = new Set(((l.modes as Record<string, { hide: string[] }>)[mode]?.hide) ?? []);
  const ctx: WidgetContext = { device, machineId, manifestId };
  return (
    <div
      className="layout-grid"
      data-screen={l.screen}
      style={{
        gridTemplateColumns: `repeat(${grid.columns}, minmax(0, 1fr))`,
        gridTemplateRows: `repeat(${grid.rows}, minmax(var(--target-min-${device}, auto), 1fr))`,
        gap: tokenVar(grid.gap_token),
      }}
    >
      {l.widgets
        .filter((w) => !hidden.has(w.id))
        .map((w) => (
          <WidgetSlot key={w.id} widget={w} ctx={ctx} />
        ))}
    </div>
  );
}
