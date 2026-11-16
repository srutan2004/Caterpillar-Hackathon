// API routes used by widgets that fetch by a selected id (§14). Routes are transport, not domain data.
const enc = encodeURIComponent;

export const routes = {
  startRecommendation: (taskId: string) => `/api/tasks/${enc(taskId)}/start-recommendation`,
  acceptRecommendation: (taskId: string) => `/api/tasks/${enc(taskId)}/start-recommendation/accept`,
  walkaround: (machineId: string) => `/api/walkaround/${enc(machineId)}`,
  walkaroundPhoto: (machineId: string) => `/api/walkaround/${enc(machineId)}/photos`,
  notes: () => "/api/notes",
  maintenanceAlert: (alertId: string) => `/api/maintenance/alerts/${enc(alertId)}`,
  maintenanceAction: (alertId: string, action: string) => `/api/maintenance/alerts/${enc(alertId)}/${enc(action)}`,
  workOrder: (alertId: string) => `/api/maintenance/alerts/${enc(alertId)}/work-order`,
  serviceDue: (machineId: string) => `/api/machines/${enc(machineId)}/service-due`,
  sensorForecast: (machineId: string, sensorId: string) => `/api/machines/${enc(machineId)}/sensors/${enc(sensorId)}/forecast`,
  incidents: () => "/api/incidents",
  incident: (incidentId: string) => `/api/incidents/${enc(incidentId)}`,
  playback: (incidentId: string) => `/api/incidents/${enc(incidentId)}/playback`,
};
