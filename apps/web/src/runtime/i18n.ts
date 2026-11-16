// i18n adapter (§14): the bundle arrives from /api/bootstrap; nothing is bundled with the app.
import i18next from "i18next";
import { initReactI18next } from "react-i18next";

let initialised = false;

export async function installI18n(locale: string, bundle: Record<string, unknown>): Promise<void> {
  if (!initialised) {
    await i18next.use(initReactI18next).init({
      lng: locale,
      resources: { [locale]: { translation: bundle } },
      interpolation: { escapeValue: false },
      returnNull: false,
    });
    initialised = true;
    return;
  }
  i18next.addResourceBundle(locale, "translation", bundle, true, true);
  await i18next.changeLanguage(locale);
}

/** Sensor ids map to keys by replacing "." with "__" (see config/i18n). */
export const sensorKey = (sensorId: string): string => `sensor.${sensorId.replace(/\./g, "__")}`;

/** Widget types map to title keys: MachineList → widget.machine_list.title */
export const widgetTitleKey = (type: string): string =>
  `widget.${type
    .replace(/([a-z])([A-Z])/g, "$1_$2")
    .replace(/([a-z])([0-9])/g, "$1_$2")
    .replace(/([A-Z])([A-Z][a-z])/g, "$1_$2")
    .toLowerCase()}.title`;
