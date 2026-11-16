import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { widgetTitleKey } from "../runtime/i18n";

export function Tile({ type, titleKey, children, tone }: { type: string; titleKey?: string; children?: ReactNode; tone?: string }) {
  const { t, i18n } = useTranslation();
  const key = titleKey ?? widgetTitleKey(type);
  return (
    <section className="tile" data-tone={tone} data-widget={type}>
      {i18n.exists(key) ? <h2 className="tile-title">{t(key)}</h2> : null}
      <div className="tile-body">{children}</div>
    </section>
  );
}
