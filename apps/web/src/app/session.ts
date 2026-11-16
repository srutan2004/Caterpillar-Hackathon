import { create } from "zustand";

interface SessionUser {
  id: string;
  name: string;
  role: string;
  locale: string;
  site_id?: string | null;
}

interface SessionState {
  token: string | null;
  user: SessionUser | null;
  device: string | null;
  signIn: (token: string, user: SessionUser) => void;
  signOut: () => void;
  setDevice: (device: string) => void;
}

const STORAGE_KEY = "tp.session";

function load(): Pick<SessionState, "token" | "user" | "device"> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Pick<SessionState, "token" | "user" | "device">;
  } catch {
    /* private mode or cleared storage: start signed out */
  }
  return { token: null, user: null, device: null };
}

function save(state: Pick<SessionState, "token" | "user" | "device">): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* storage unavailable: session lasts for this tab only */
  }
}

export const useSession = create<SessionState>((set, get) => ({
  ...load(),
  signIn: (token, user) => {
    set({ token, user });
    save({ token, user, device: get().device });
  },
  signOut: () => {
    set({ token: null, user: null });
    save({ token: null, user: null, device: get().device });
  },
  setDevice: (device) => {
    set({ device });
    save({ token: get().token, user: get().user, device });
  },
}));
