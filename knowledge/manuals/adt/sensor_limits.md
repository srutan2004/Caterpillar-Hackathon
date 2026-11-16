---
machine_class: adt
section: sensor_limits
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.826570+00:00'
---

## Sensor Limits and Alert Responses  
*Section: sensor_limits*  

The articulated dump truck is equipped with a suite of diagnostic sensors that continuously monitor the health of critical systems. Each sensor can generate three alert tiers – **Info**, **Service Soon**, and **Stop** – plus optional **Forecast** warnings when a trend indicates an imminent limit breach. Understanding what each tier means and how the operator must respond is essential for safe operation and timely maintenance.

---

### PROCEDURE P001: General Alert Tier Definitions  

| Alert Tier | Meaning | Immediate Operator Action |
|------------|---------|---------------------------|
| **Info** | Parameter is within normal operating range. | No action required other than routine monitoring. |
| **Service Soon** | Parameter is approaching a defined limit but the machine can still be operated safely for a limited period. | Log the condition, notify the shift supervisor, and schedule maintenance at the next convenient opportunity (no later than the next shift change). |
| **Stop** | Parameter has exceeded a critical limit. Continued operation could cause damage or unsafe conditions. | **> **WARNING:**<br>Stop the machine immediately, engage the parking brake, and follow the emergency shutdown procedure (see **Procedure P010**). Contact maintenance before restarting. |
| **Forecast** *(optional)* | Sensor trend analysis predicts that a limit will be reached within a defined future interval. | Treat as **Service Soon** but prioritize the affected component for inspection before the predicted time. |

> **NOTE:** The exact numeric thresholds for each sensor are defined in the referenced *maintenance/sensor_limits.yaml* file. Operators do **not** need to memorize the numbers; they must recognize the alert tier displayed on the cab display.

---

### PROCEDURE P002: Engine Coolant Temperature – `engine.coolant_temp`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#coolant_temp` – upper warning limit |
| Stop | `maintenance/sensor_limits.yaml#coolant_temp` – critical limit |
| Forecast | Enabled (`forecast: true`) – predicts overheating trend |

**Operator Actions**  

1. **Info** – Continue operation; verify that the temperature gauge remains stable.  
2. **Service Soon** – Reduce load (e.g., avoid full‑grade climbs), increase idle time to allow cooling, and log the event.  
3. **Forecast** – Same as Service Soon, but arrange a coolant system inspection before the predicted exceedance.  
4. **Stop** – Pull the truck to a safe area, shut off the engine, and follow **Procedure P010**.

---

### PROCEDURE P003: Engine Oil Pressure (RPM‑Normalized) – `engine.oil_pressure`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#oil_pressure_vs_rpm` – low‑pressure warning curve |
| Stop | `maintenance/sensor_limits.yaml#oil_pressure_vs_rpm` – critical low‑pressure curve |
| Forecast | Not configured (no forecast flag) |

**Operator Actions**  

1. **Info** – No action.  
2. **Service Soon** – Reduce engine RPM, avoid high‑load cycles, and schedule an oil system check.  
3. **Stop** – Immediately cease engine operation, engage the parking brake, and contact service. Do not restart until oil pressure is verified.  

> **WARNING:** Operating with low oil pressure can cause catastrophic engine wear.

---

### PROCEDURE P004: Engine Air‑Filter Restriction – `engine.air_filter_restriction`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#air_restriction` – moderate restriction |
| Stop | `maintenance/sensor_limits.yaml#air_restriction` – severe blockage |
| Forecast | Enabled (`forecast: true`) – predicts when restriction will reach stop level |

**Operator Actions**  

1. **Info** – Monitor for dust conditions.  
2. **Service Soon** – Increase filter inspection frequency; clean or replace filter at the next scheduled service.  
3. **Forecast** – Prioritize filter replacement before the predicted stop condition.  
4. **Stop** – Shut down engine, ventilate the cab, and replace the filter before any further operation.

---

### PROCEDURE P005: DPF Soot Load – `dpf.soot_load_pct`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#dpf_soot` – high soot percentage |
| Stop | `maintenance/sensor_limits.yaml#dpf_soot` – maximum allowable soot |
| Forecast | Enabled (`forecast: true`) – predicts when soot will exceed stop limit |

**Operator Actions**  

1. **Info** – Continue normal operation.  
2. **Service Soon** – Initiate a regeneration cycle if the system permits; otherwise, plan a DPF cleaning at the next service window.  
3. **Forecast** – Schedule regeneration or cleaning before the forecasted exceedance.  
4. **Stop** – Cease operation, activate the DPF purge (if available), and call service. Do not restart until soot load is reduced.

---

### PROCEDURE P006: Transmission Oil Temperature – `transmission.oil_temp`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#transmission_temp` – elevated temperature |
| Stop | `maintenance/sensor_limits.yaml#transmission_temp` – critical temperature |
| Forecast | Enabled (`forecast: true`) – predicts overheating trend |

**Operator Actions**  

1. **Info** – No action.  
2. **Service Soon** – Reduce transmission load (avoid rapid shifts, lower hill climbs), allow cooling, and log for service.  
3. **Forecast** – Same as Service Soon, but arrange a transmission oil inspection before the predicted time.  
4. **Stop** – Stop the vehicle, shift to neutral, wait for temperature to fall below the stop limit, then follow **Procedure P010** before restarting.

---

### PROCEDURE P007: Brake Temperature – `brakes.temp`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#brake_temp` – warm but safe |
| Stop | `maintenance/sensor_limits.yaml#brake_temp` – overheated brake |
| Forecast | Not configured |

**Operator Actions**  

1. **Info** – Continue normal braking.  
2. **Service Soon** – Allow brakes to cool by reducing repeated heavy braking; plan a brake inspection.  
3. **Stop** – Pull to a safe area, let brakes cool completely, and do **not** resume operation until a qualified technician verifies brake integrity.

> **WARNING:** Overheated brakes can lead to fade and loss of stopping power.

---

### PROCEDURE P008: Tyre Pressure – `tyre.pressure_kpa`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#tyre_pressure_adt` – low‑pressure warning |
| Stop | `maintenance/sensor_limits.yaml#tyre_pressure_adt` – unsafe pressure |
| Forecast | Enabled (`forecast: true`) – predicts pressure loss (e.g., leak) |

**Operator Actions**  

1. **Info** – Verify pressure reading matches expected value.  
2. **Service Soon** – Inflate to recommended pressure, inspect for slow leaks, and schedule a tyre inspection.  
3. **Forecast** – Treat as Service Soon but prioritize tyre inspection before the predicted loss.  
4. **Stop** – Do not drive; inflate to minimum safe pressure if possible, then arrange immediate tyre service.

---

### PROCEDURE P009: Tyre Temperature – `tyre.temp`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#tyre_temp` – elevated temperature |
| Stop | `maintenance/sensor_limits.yaml#tyre_temp` – dangerously hot tyre |
| Forecast | Not configured |

**Operator Actions**  

1. **Info** – Continue operation.  
2. **Service Soon** – Reduce speed, avoid prolonged high‑load runs, and inspect tyres at next service.  
3. **Stop** – Pull over, allow tyres to cool, and do not restart until a qualified technician confirms tyre integrity.

---

### PROCEDURE P010: Axle Strut Pressure – `suspension.strut_pressure`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#strut_pressure` – pressure drift |
| Stop | `maintenance/sensor_limits.yaml#strut_pressure` – out‑of‑range pressure |
| Forecast | Not configured |

**Operator Actions**  

1. **Info** – No action.  
2. **Service Soon** – Note the pressure deviation, avoid extreme loads, and arrange a suspension check.  
3. **Stop** – Cease operation, engage parking brake, and request immediate suspension service. Operating with incorrect strut pressure can affect vehicle stability.

---

### PROCEDURE P011: Water in Fuel – `fuel.water_in_fuel`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#wif` – detectable water content |
| Stop | `maintenance/sensor_limits.yaml#wif` – water exceeds safe limit |
| Forecast | Not configured |

**Operator Actions**  

1. **Info** – Continue operation; monitor fuel quality.  
2. **Service Soon** – Schedule fuel filter change and fuel tank drainage at the next service.  
3. **Stop** – Stop the engine, drain the fuel tank, replace the filter, and verify water content is below the service‑soon limit before restarting.

> **WARNING:** Water in fuel can cause injector damage and engine mis‑fire.

---

### PROCEDURE P012: Electrical System Voltage – `electrical.system_voltage`  

| Tier | Limit Reference |
|------|-----------------|
| Service Soon | `maintenance/sensor_limits.yaml#sys_voltage` – marginal voltage drop |
| Stop | `maintenance/sensor_limits.yaml#sys_voltage` – voltage below safe operating level |
| Forecast | Not configured |

**Operator Actions**  

1. **Info** – No action.  
2. **Service Soon** – Check battery connections, clean terminals, and plan a charging system inspection.  
3. **Stop** – Shut down non‑essential loads, park the vehicle, and contact electrical service. Do not restart critical systems until voltage is restored.

---

### PROCEDURE P013: Monitoring & Logging Workflow  

1. At start‑up, verify that the **Sensor Status Panel** displays all sensors as **OK** (green).  
2. During operation, glance at the panel every 15 minutes; any amber or red icon indicates **Service Soon** or **Stop** respectively.  
3. When an amber icon appears:  
   - Press the **Acknowledge** button to record the event.  
   - Enter a brief comment (e.g., “high coolant temp – reduced load”).  
   - Notify the shift supervisor.  
4. When a red icon appears:  
   - Press **Acknowledge** (if safe) and immediately follow **Procedure P010** (Emergency Stop).  
   - Record the exact sensor ID and displayed value in the **Incident Log**.  
5. At the end of the shift, export the **Sensor Log** to the maintenance management system for trend analysis and forecast verification.  

---

### PROCEDURE P014: Forecast Alert Handling  

Forecast alerts are generated by the on‑board analytics module when a sensor’s trend line intersects a future limit within a predefined horizon (typically a future interval).  

| Forecast Type | Recommended Response |
|---------------|----------------------|
| **Temperature rise** (coolant, transmission, tyre) | Reduce load, increase idle cooling, and schedule inspection before the predicted time. |
| **Pressure loss** (tyre, strut) | Inflate to safe pressure, inspect for leaks, and arrange service. |
| **Soot load increase** (DPF) | Initiate regeneration early, or plan a DPF cleaning. |
| **Water in fuel trend** | Drain fuel and replace filter ahead of schedule. |

> **NOTE:** Forecast alerts never require an immediate stop, but ignoring them can quickly convert a **Service Soon** condition into a **Stop**.

---

### PROCEDURE P015: Summary Checklist for Operators  

| Item | Completed? |
|------|------------|
| Visual check of sensor panel at start‑up | ☐ |
| Acknowledge any **Info** alerts (none required) | ☐ |
| Record and act on any **Service Soon** alerts | ☐ |
| Execute **Stop** procedure for any red alerts | ☐ |
| Review forecast alerts and prioritize inspections | ☐ |
| Log all actions in the shift report | ☐ |
| Export sensor log to maintenance system | ☐ |

Following these procedures ensures that sensor‑based alerts are interpreted correctly, that the vehicle remains within safe operating limits, and that maintenance can be planned proactively, minimizing downtime and protecting critical components.
