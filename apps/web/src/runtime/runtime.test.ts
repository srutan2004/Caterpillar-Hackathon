import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";

import { widgetTitleKey } from "./i18n";
import { getPath, setPath } from "./live";
import { registry } from "./registry";
import { themeVariables, type ThemeConfig } from "./theme";
import { formatValue, type UnitsConfig } from "./units";

const CONFIG = resolve(__dirname, "../../../../config");
const yaml = (rel: string) => parse(readFileSync(resolve(CONFIG, rel), "utf-8"));

describe("widget registry", () => {
  it("matches config/ui/widgets.yaml exactly", () => {
    const declared = (yaml("ui/widgets.yaml").types as string[]).slice().sort();
    expect(Object.keys(registry).sort()).toEqual(declared);
  });

  it("maps widget types to i18n title keys", () => {
    expect(widgetTitleKey("MachineList")).toBe("widget.machine_list.title");
    expect(widgetTitleKey("Twin3D")).toBe("widget.twin_3d.title");
    expect(widgetTitleKey("LlmStatusTile")).toBe("widget.llm_status_tile.title");
  });
});

describe("theme adapter", () => {
  it("emits CSS variables from tokens and picks the device variant", () => {
    const theme = yaml("theme.yaml") as ThemeConfig;
    const cab = themeVariables(theme, "cab");
    const desk = themeVariables(theme, "desk");
    expect(cab["--space-2"]).toBe(theme.space ? (theme.space as Record<string, string>)["2"] : undefined);
    expect(cab["--color-bg"]).toBe((theme.variants.dark.color as Record<string, string>).bg);
    expect(desk["--color-bg"]).toBe((theme.variants.light.color as Record<string, string>).bg);
    expect(cab["--alert-warning-bg"]).toBeDefined();
    expect(cab["--font-size-md"]).toBeDefined();
  });
});

describe("formatValue", () => {
  const units = { system: "metric", quantities: yaml("units.yaml").systems.metric.quantities } as UnitsConfig;
  it("converts SI to display units", () => {
    expect(formatValue(units, "temperature", 300, "en")).toBe("27 °C");
    expect(formatValue(units, "ratio", 0.125, "en")).toBe("13 %");
    expect(formatValue(units, "pressure", 3.2e7, "en")).toBe("320 bar");
    expect(formatValue(units, "speed", null, "en")).toBe("—");
  });
  it("handles offset units in imperial", () => {
    const imperial = { system: "imperial", quantities: yaml("units.yaml").systems.imperial.quantities } as UnitsConfig;
    expect(formatValue(imperial, "temperature", 300, "en")).toBe("80 °F");
  });
});

describe("live store paths", () => {
  it("sets nested paths immutably", () => {
    const a = { hydraulic: { pump_pressure: 1 } };
    const b = setPath(a, "hydraulic.oil_temp", 60);
    expect(getPath(b, "hydraulic.pump_pressure")).toBe(1);
    expect(getPath(b, "hydraulic.oil_temp")).toBe(60);
    expect(getPath(a, "hydraulic.oil_temp")).toBeUndefined();
  });
});
