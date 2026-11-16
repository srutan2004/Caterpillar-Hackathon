import { useState } from "react";
import { useTranslation } from "react-i18next";
import { generatePath, useNavigate } from "react-router-dom";

import { api, ApiError, type MachineOut, type MachineSelectResponse } from "../api/client";
import { useBootstrap } from "../app/bootstrap";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

function cell(m: MachineOut, col: string, t: (k: string) => string): string {
  switch (col) {
    case "model":
      return t(m.model_key);
    case "status":
      return t(`machine.status.${m.status}`);
    case "powertrain":
      return t(`machine.powertrain.${m.powertrain}`);
    default:
      return String((m as unknown as Record<string, unknown>)[col] ?? "");
  }
}

export function MachineList({ widget, binding, props }: WidgetProps) {
  const { t, i18n } = useTranslation();
  const boot = useBootstrap();
  const navigate = useNavigate();
  const [selection, setSelection] = useState<MachineSelectResponse | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const machines = (binding.value as MachineOut[] | undefined) ?? [];
  const columns = (props.columns as string[] | undefined) ?? ["id"];
  const selectable = props.on_select === "open_cockpit";
  const cockpit = boot?.nav.find((n) => n.id === "cockpit");
  const training = boot?.nav.find((n) => n.id === "training");

  const select = async (id: string) => {
    setErrorKey(null);
    try {
      setSelection(await api<MachineSelectResponse>("/api/auth/machine-select", { method: "POST", body: JSON.stringify({ machine_id: id }) }));
    } catch (err) {
      setErrorKey(err instanceof ApiError ? err.messageKey : "app.error_generic");
    }
  };

  return (
    <Tile type={widget.type}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{t(`widget.machine_list.columns.${c}`)}</th>
            ))}
            {selectable ? <th /> : null}
          </tr>
        </thead>
        <tbody>
          {machines.map((m) => (
            <tr key={m.id} data-selected={selection?.machine.id === m.id}>
              {columns.map((c) => (
                <td key={c}>{cell(m, c, t)}</td>
              ))}
              {selectable ? (
                <td>
                  <button type="button" onClick={() => void select(m.id)}>
                    {t("widget.machine_list.select")}
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {errorKey ? <p className="form-error">{t(errorKey)}</p> : null}
      {selection ? (
        <div className="gating" data-status={selection.gating.status}>
          <p>
            <strong>{selection.machine.id}</strong>
            <span className="dash" />
            {t(`gating.${selection.gating.status}`)}
          </p>
          <ul>
            {selection.gating.modules.map((mod) => (
              <li key={mod.module_id} data-status={mod.status}>
                {t(mod.title_key ?? mod.module_id)}
                <span className="dash" />
                {t(`gating.module.${mod.status}`)}
                {mod.expires_at ? (
                  <>
                    <span className="sep" />
                    {t("gating.expires_on", { date: new Date(mod.expires_at).toLocaleDateString(i18n.language) })}
                  </>
                ) : null}
              </li>
            ))}
          </ul>
          {selection.gating.status !== "blocked" && cockpit ? (
            <button type="button" onClick={() => navigate(generatePath(cockpit.path, { machineId: selection.machine.id }))}>
              {t("gating.continue")}
            </button>
          ) : null}
          {selection.gating.status === "blocked" && training ? (
            <button type="button" onClick={() => navigate(training.path)}>
              {t("gating.book")}
            </button>
          ) : null}
        </div>
      ) : null}
    </Tile>
  );
}
