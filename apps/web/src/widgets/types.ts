import type { ComponentType } from "react";
import type { ZodTypeAny } from "zod";

import type { ResolvedWidget } from "../api/client";
import type { Binding } from "../runtime/binding";

export interface WidgetContext {
  machineId?: string;
  manifestId?: string;
  device: string;
}

export interface WidgetProps {
  widget: ResolvedWidget;
  binding: Binding;
  props: Record<string, unknown>;
  ctx: WidgetContext;
}

export interface WidgetDef {
  component: ComponentType<WidgetProps>;
  props: ZodTypeAny;
}
