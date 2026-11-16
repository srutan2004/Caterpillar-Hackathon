// Boot (§14): nothing renders until /api/bootstrap resolves; then theme, i18n and router are installed.
import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api, type Bootstrap } from "../api/client";
import { installI18n } from "../runtime/i18n";
import { applyTheme, type ThemeConfig } from "../runtime/theme";
import { secondsToMs } from "../runtime/time";
import { useSession } from "./session";

const BootstrapContext = createContext<Bootstrap | null>(null);

export const useBootstrap = (): Bootstrap | null => useContext(BootstrapContext);

export function currentDevice(boot: Bootstrap, stored: string | null): string {
  const fromUrl = new URLSearchParams(window.location.search).get("device");
  const candidates = [fromUrl, stored, boot.ui.default_device];
  return candidates.find((d): d is string => !!d && boot.ui.devices.includes(d)) ?? boot.ui.default_device;
}

export function BootstrapProvider({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const token = useSession((s) => s.token);
  const storedDevice = useSession((s) => s.device);
  const [ready, setReady] = useState<Bootstrap | null>(null);
  const query = useQuery({
    queryKey: ["bootstrap", token],
    queryFn: () => api<Bootstrap>("/api/bootstrap"),
  });

  useEffect(() => {
    const boot = query.data;
    if (!boot) return;
    let cancelled = false;
    applyTheme(boot.theme as unknown as ThemeConfig, currentDevice(boot, storedDevice));
    document.title = boot.product.name as string;
    void installI18n(boot.locale, boot.i18n).then(() => {
      if (!cancelled) setReady(boot);
    });
    return () => {
      cancelled = true;
    };
  }, [query.data, storedDevice]);

  useEffect(() => {
    const seconds = ready?.refresh.bootstrap_s as number | undefined;
    if (!seconds) return undefined;
    const id = setInterval(() => void query.refetch(), secondsToMs(seconds));
    return () => clearInterval(id);
  }, [ready, query]);

  if (!ready) return <>{fallback}</>;
  return <BootstrapContext.Provider value={ready}>{children}</BootstrapContext.Provider>;
}
