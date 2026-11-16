// App shell: router built from bootstrap.nav (§14). Screens are layouts; the app knows no screen by name
// except the generic parameters a screen declares (`requires: [machine]`).
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useParams } from "react-router-dom";

import { api, type MachineOut, type NavItem } from "../api/client";
import { LayoutRenderer } from "../runtime/LayoutRenderer";
import { useMachineSocket } from "../runtime/ws";
import { useLive } from "../runtime/live";
import { currentDevice, useBootstrap } from "./bootstrap";
import { useSession } from "./session";

function Chrome({ item, device }: { item: NavItem; device: string }) {
  const { t } = useTranslation();
  const boot = useBootstrap();
  const user = useSession((s) => s.user);
  const signOut = useSession((s) => s.signOut);
  const setDevice = useSession((s) => s.setDevice);
  if (!boot || !item.chrome) return null;
  return (
    <header className="app-header">
      <span className="app-brand">{boot.product.name as string}</span>
      <nav className="app-nav">
        {boot.nav
          .filter((n) => n.in_menu)
          .map((n) => (
            <NavLink key={n.id} to={n.path}>
              {t(n.label_key)}
            </NavLink>
          ))}
      </nav>
      <label className="device-select">
        <span className="sr-only">{t("app.device")}</span>
        <select value={device} onChange={(e) => setDevice(e.target.value)}>
          {boot.ui.devices.map((d) => (
            <option key={d} value={d}>
              {t(`device.${d}`)}
            </option>
          ))}
        </select>
      </label>
      {user ? (
        <span className="app-user">
          {t("app.signed_in_as", { name: user.name, role: t(`role.${user.role}`) })}
          <button type="button" onClick={signOut}>
            {t("app.sign_out")}
          </button>
        </span>
      ) : null}
    </header>
  );
}

function MachineScreen({ item, device }: { item: NavItem; device: string }) {
  const { machineId } = useParams();
  const { t } = useTranslation();
  const machine = useQuery({
    queryKey: ["machine", machineId],
    queryFn: () => api<MachineOut>(`/api/machines/${machineId ?? ""}`),
    enabled: !!machineId,
  });
  useMachineSocket(machineId);
  const connected = useLive((s) => s.connected);

  // Auto-start a scenario for this machine so the cockpit gets live data (§18 demo flow).
  useQuery({
    queryKey: ["auto_scenario", machineId],
    queryFn: () => api(`/api/machines/${machineId}/demo`, { method: "POST" }),
    enabled: !!machineId && item.id === "cockpit",
    retry: false,
    staleTime: Infinity,
  });

  if (!machine.data) return <p className="muted">{t(machine.isError ? "error.not_found" : "app.loading")}</p>;
  return (
    <>
      {!connected ? (
        <div className="offline-banner" role="status">
          {t("app.offline_banner")}
        </div>
      ) : null}
      <LayoutRenderer screen={item.id} device={device} manifestId={machine.data.manifest_id} machineId={machine.data.id} />
    </>
  );
}


function Screen({ item }: { item: NavItem }) {
  const boot = useBootstrap();
  const storedDevice = useSession((s) => s.device);
  if (!boot) return null;
  const device = currentDevice(boot, storedDevice);
  return (
    <div className="app" data-device={device}>
      <Chrome item={item} device={device} />
      <main className="app-main">
        {item.requires.includes("machine") ? (
          <MachineScreen item={item} device={device} />
        ) : (
          <LayoutRenderer screen={item.id} device={device} />
        )}
      </main>
    </div>
  );
}

export function App() {
  const boot = useBootstrap();
  if (!boot) return null;
  const home = boot.nav.find((n) => n.id === boot.ui.default_screen) ?? boot.nav[0];
  return (
    <BrowserRouter>
      <Routes>
        {boot.nav.map((n) => (
          <Route key={n.id} path={n.path} element={<Screen item={n} />} />
        ))}
        <Route path="*" element={<Navigate to={home.path} replace />} />
      </Routes>
    </BrowserRouter>
  );
}
