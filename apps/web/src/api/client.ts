import type { components } from "./schema";
import { useSession } from "../app/session";

type Schemas = components["schemas"];
export type Bootstrap = Schemas["Bootstrap"];
export type LayoutOut = Schemas["LayoutOut"];
export type ResolvedWidget = Schemas["ResolvedWidget"];
export type FormOut = Schemas["FormOut"];
export type MachineOut = Schemas["MachineOut"];
export type LoginResponse = Schemas["LoginResponse"];
export type MachineSelectResponse = Schemas["MachineSelectResponse"];
export type NavItem = Schemas["NavItem"];
export type WsMessage = Schemas["WsEnvelope"]["message"];

// The single allowed frontend configuration value (§2.1).
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly messageKey: string,
  ) {
    super(messageKey);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = useSession.getState().token;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let key = "app.error_generic";
    try {
      const body = (await res.json()) as { detail?: { message_key?: string } };
      key = body.detail?.message_key ?? key;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === UNAUTHORIZED && token) useSession.getState().signOut();
    throw new ApiError(res.status, key);
  }
  return (await res.json()) as T;
}

const UNAUTHORIZED = 401;

export function wsUrl(path: string, token: string): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  return `${base}${path}?token=${encodeURIComponent(token)}`;
}
