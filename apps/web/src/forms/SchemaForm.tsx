// RJSF wrapper (§14): every `title` in the server schema is an i18n key and is translated here;
// validation messages map to i18n keys too, so the form carries no literal text.
import Form from "@rjsf/core";
import type { RJSFValidationError, UiSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";
import type { TFunction } from "i18next";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { FormOut } from "../api/client";

type Schema = Record<string, unknown>;

export function translateSchema(schema: Schema, t: TFunction): Schema {
  const out: Schema = {};
  for (const [key, value] of Object.entries(schema)) {
    if (key === "title" && typeof value === "string") out[key] = t(value);
    else if (Array.isArray(value)) out[key] = value.map((v) => (v && typeof v === "object" ? translateSchema(v as Schema, t) : v));
    else if (value && typeof value === "object") out[key] = translateSchema(value as Schema, t);
    else out[key] = value;
  }
  return out;
}

interface Props {
  form: FormOut;
  busy?: boolean;
  errorKey?: string | null;
  onSubmit: (data: Record<string, unknown>) => void;
}

export function SchemaForm({ form, busy, errorKey, onSubmit }: Props) {
  const { t } = useTranslation();
  // Controlled: RJSF re-derives state from props.formData whenever props change (e.g. `busy`),
  // so an uncontrolled form would lose what the user typed.
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const schema = useMemo(() => translateSchema(form.schema as Schema, t), [form.schema, t]);
  const uiSchema: UiSchema = useMemo(
    () => ({ ...(form.ui_schema as UiSchema), "ui:submitButtonOptions": { submitText: t(form.submit_key), props: { disabled: busy } } }),
    [form.ui_schema, form.submit_key, busy, t],
  );
  const transformErrors = (errors: RJSFValidationError[]) =>
    errors.map((e) => ({ ...e, message: t(`validation.${e.name ?? "generic"}`, { defaultValue: t("validation.generic") }) }));
  return (
    <div className="schema-form">
      <h2>{t(form.title_key)}</h2>
      <Form
        schema={schema}
        uiSchema={uiSchema}
        validator={validator}
        formData={formData}
        onChange={({ formData: next }) => setFormData((next ?? {}) as Record<string, unknown>)}
        showErrorList={false}
        transformErrors={transformErrors}
        onSubmit={({ formData }) => onSubmit(formData as Record<string, unknown>)}
        noHtml5Validate
      />
      {errorKey ? (
        <p className="form-error" role="alert">
          {t(errorKey)}
        </p>
      ) : null}
    </div>
  );
}
