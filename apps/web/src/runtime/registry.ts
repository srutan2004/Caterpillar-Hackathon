// Widget registry (§14). Keys must match config/ui/widgets.yaml exactly (asserted by registry.test.ts).
// Widget type names are the only domain-free identifiers allowed in frontend code (§2.1).
import { z } from "zod";

import { AlertStack, AppBrand, LlmStatusTile, ScreenHeader, UnknownWidget } from "../widgets/basic";
import { CopilotBanner, EnergyCard, Gauge, GradeProfile, ProximityRadar, StabilityDial, TaskProgress, Twin3D } from "../widgets/live";
import { FormView } from "../widgets/FormView";
import { MachineList } from "../widgets/MachineList";
import { ChatPanel } from "../widgets/chat";
import { AvailabilityChart, Gantt, HealthList, KpiTile } from "../widgets/fleet";
import { QuizWidget, SlotCalendar, TrainingHub } from "../widgets/training";
import { CabNotes, FactorBars, PacingGauge, PreconditionChecklist, ReadinessBadge, StartTimeCurve, TaskTimeline, Walkaround } from "../widgets/day";
import { IncidentPlayback } from "../widgets/incidents";
import { MaintenanceAlertCard, SensorForecastChart, ServiceCountdown } from "../widgets/maintenance";
import { DashboardStats, EvalSummary, FleetStatusBoard, ScenarioPlayer } from "../widgets/dashboard";
import {
  AnomalyBoard,
  ComplianceBoard,
  DataTable,
  MaintenanceCalendar,
  MapView,
  SimViewport,
  TaskCard,
  VideoPlayer,
} from "../widgets/supervisor";
import type { WidgetDef } from "../widgets/types";

const anyProps = z.object({}).passthrough();

export const registry: Record<string, WidgetDef> = {
  AppBrand: { component: AppBrand, props: anyProps },
  ScreenHeader: { component: ScreenHeader, props: z.object({ title_key: z.string(), subtitle_key: z.string().optional() }) },
  FormView: { component: FormView, props: z.object({ form_id: z.string(), action: z.string(), on_success: z.string().optional() }) },
  MachineList: { component: MachineList, props: z.object({ columns: z.array(z.string()), on_select: z.string().optional() }) },
  AlertStack: { component: AlertStack, props: anyProps },
  CopilotBanner: { component: CopilotBanner, props: anyProps },
  Gauge: { component: Gauge, props: anyProps },
  LlmStatusTile: { component: LlmStatusTile, props: anyProps },
  StabilityDial: { component: StabilityDial, props: anyProps },
  ProximityRadar: { component: ProximityRadar, props: anyProps },
  Twin3D: { component: Twin3D, props: anyProps },
  GradeProfile: { component: GradeProfile, props: anyProps },
  TaskProgress: { component: TaskProgress, props: anyProps },
  EnergyCard: { component: EnergyCard, props: anyProps },
  Walkaround: { component: Walkaround, props: anyProps },
  CabNotes: { component: CabNotes, props: anyProps },
  TaskTimeline: { component: TaskTimeline, props: anyProps },
  TaskCard: { component: TaskCard, props: anyProps },
  PacingGauge: { component: PacingGauge, props: anyProps },
  HealthList: { component: HealthList, props: anyProps },
  ChatPanel: { component: ChatPanel, props: anyProps },
  VideoPlayer: { component: VideoPlayer, props: anyProps },
  Quiz: { component: QuizWidget, props: anyProps },
  TrainingHub: { component: TrainingHub, props: anyProps },
  SlotCalendar: { component: SlotCalendar, props: anyProps },
  SimViewport: { component: SimViewport, props: anyProps },
  IncidentPlayback: { component: IncidentPlayback, props: anyProps },
  MapView: { component: MapView, props: anyProps },
  ComplianceBoard: { component: ComplianceBoard, props: anyProps },
  AnomalyBoard: { component: AnomalyBoard, props: anyProps },
  Gantt: { component: Gantt, props: anyProps },
  KpiTile: { component: KpiTile, props: anyProps },
  DataTable: { component: DataTable, props: anyProps },
  MaintenanceAlertCard: { component: MaintenanceAlertCard, props: anyProps },
  SensorForecastChart: { component: SensorForecastChart, props: anyProps },
  ServiceCountdown: { component: ServiceCountdown, props: anyProps },
  ReadinessBadge: { component: ReadinessBadge, props: anyProps },
  StartTimeCurve: { component: StartTimeCurve, props: anyProps },
  PreconditionChecklist: { component: PreconditionChecklist, props: anyProps },
  FactorBars: { component: FactorBars, props: anyProps },
  MaintenanceCalendar: { component: MaintenanceCalendar, props: anyProps },
  AvailabilityChart: { component: AvailabilityChart, props: anyProps },
  ScenarioPlayer: { component: ScenarioPlayer, props: anyProps },
  DashboardStats: { component: DashboardStats, props: anyProps },
  EvalSummary: { component: EvalSummary, props: anyProps },
  FleetStatusBoard: { component: FleetStatusBoard, props: anyProps },
};

export const unknownWidget: WidgetDef = { component: UnknownWidget, props: anyProps };

export function resolveWidget(type: string): WidgetDef {
  return registry[type] ?? unknownWidget;
}
