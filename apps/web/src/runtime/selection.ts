// Cross-widget selection (§14): a widget that lists things publishes the selected id; detail widgets read it.
// Ids only — never domain data.
import { create } from "zustand";

interface SelectionState {
  taskId: string | null;
  alertId: string | null;
  machineId: string | null;
  siteId: string | null;
  incidentId: string | null;
  select: (patch: Partial<Omit<SelectionState, "select">>) => void;
}

export const useSelection = create<SelectionState>((set) => ({
  taskId: null,
  alertId: null,
  machineId: null,
  siteId: null,
  incidentId: null,
  select: (patch) => set(patch),
}));
