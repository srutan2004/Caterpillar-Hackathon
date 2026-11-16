import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type FormOut, type LoginResponse } from "../api/client";
import { useSession } from "../app/session";
import { SchemaForm } from "../forms/SchemaForm";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

export function FormView({ widget, props }: WidgetProps) {
  const { t } = useTranslation();
  const formId = String(props.form_id);
  const signIn = useSession((s) => s.signIn);
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [doneKey, setDoneKey] = useState<string | null>(null);
  const form = useQuery({ queryKey: ["form", formId], queryFn: () => api<FormOut>(`/api/ui/forms/${formId}`) });

  if (!form.data) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(form.isError ? "app.error_generic" : "app.loading")}</p>
      </Tile>
    );
  }
  const f = form.data;

  const submit = async (data: Record<string, unknown>) => {
    setBusy(true);
    setErrorKey(null);
    try {
      const result = await api<unknown>(f.action.path, { method: f.action.method, body: JSON.stringify(data) });
      if (props.action === "auth.login") {
        const login = result as LoginResponse;
        signIn(login.access_token, login.user);
        await qc.invalidateQueries();
      } else {
        setDoneKey(f.title_key);
      }
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      const mapped = (f.errors as Record<string, string>)[String(status)];
      setErrorKey(mapped ?? (err instanceof ApiError ? err.messageKey : "app.error_generic"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="form-view">
      <SchemaForm form={f} busy={busy} errorKey={errorKey} onSubmit={(d) => void submit(d)} />
      {doneKey ? <p className="muted">{t(doneKey)}</p> : null}
    </div>
  );
}
