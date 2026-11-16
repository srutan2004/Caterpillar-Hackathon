---
machine_class: wheel_loader
section: sensor_limits
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.876949+00:00'
---

# Sensor Limits and Alert Responses  
*Section: sensor_limits*  

This section explains the meaning of each maintenance‑alert tier that can appear on the wheel‑loader’s display, the actions the operator must take when an alert is shown, and the recommended service response. All alerts are generated from the sensor list defined in the machine’s **maintenance_sensors** table (see the SPEC VALUES block).  

---  

## Alert Tiers Overview  

| Tier | Display Symbol | Meaning | Immediate Operator Action |
|------|----------------|---------|----------------------------|
| **Info** | “i” in a blue circle | Parameter is within normal operating range. No action required. | Continue normal operation. |
| **Caution** | “!” in a yellow triangle | Parameter is approaching a defined limit. Continue operation but monitor closely. | Observe the parameter, prepare to act if it escalates to **Service Soon**. |
| **Service Soon** | “!” in an orange diamond | Parameter has exceeded the **caution** threshold and is moving toward a critical limit. Machine can still be used, but service is required soon. | Reduce load if possible, log the condition, and schedule service before the next shift ends. |
| **Stop** | “X” in a red circle | Parameter has reached a critical limit that could cause damage or unsafe operation. The machine will automatically inhibit further operation of the affected subsystem. | Immediately cease the activity that triggered the alert, follow the **Stop** procedure for that sensor, and contact maintenance. |

> **WARNING:** Ignoring a **Stop** alert can result in component failure, loss of machine availability, or personal injury.  

---  

## PROCEDURE P001: Engine Coolant Temperature (engine.coolant_temp)  

**Component:** Cooling system  
**Limits Reference:** `maintenance/sensor_limits.yaml#coolant_temp` (forecast enabled)  

1. **Caution** – Temperature is rising toward the high‑temperature limit.  
   - Reduce engine load (e.g., lower lift height, avoid full‑throttle operation).  
   - Verify that the radiator fan is operating.  

2. **Service Soon** – Temperature has exceeded the caution threshold.  
   - Stop the machine in a safe location.  
   - Allow the engine to idle for at least 2 minutes to stabilize temperature.  
   - Record the temperature reading and time of occurrence in the logbook.  
   - Contact service personnel to inspect coolant level, radiator blockage, and fan operation.  

3. **Stop** – Temperature has reached the critical limit.  
   - The loader will automatically limit engine power and display a red **Stop** alert.  
   - Immediately shut off the engine, wait for cooling, and do not restart until a qualified technician has cleared the fault.  

---  

## PROCEDURE P002: Engine Oil Pressure (engine.oil_pressure)  

**Component:** Engine  
**Limits Reference:** `maintenance/sensor_limits.yaml#oil_pressure_vs_rpm` (normalised by engine.rpm)  

1. **Caution** – Oil pressure is dropping relative to RPM.  
   - Reduce engine speed and load.  
   - Check oil level after the machine is stopped.  

2. **Service Soon** – Pressure is below the normalised caution limit.  
   - Stop the machine, allow the engine to cool, and inspect oil level and condition.  
   - If oil level is adequate, schedule a full oil‑system inspection (pump, filter, pressure sensor).  

3. **Stop** – Pressure has fallen to the critical limit.  
   - Engine power will be limited and a red **Stop** alert will appear.  
   - Shut down the engine immediately. Do **not** restart until the oil pressure system has been repaired and verified.  

---  

## PROCEDURE P003: Hydraulic Oil Temperature (hydraulic.oil_temp)  

**Component:** Hydraulic pump  
**Limits Reference:** `maintenance/sensor_limits.yaml#hyd_oil_temp` (forecast enabled)  

1. **Caution** – Temperature approaching the high‑temp limit.  
   - Reduce hydraulic demand (lower lift speed, avoid rapid cycling).  

2. **Service Soon** – Temperature exceeds the caution threshold.  
   - Park the loader, let the hydraulic system idle for 3 minutes.  
   - Record the temperature and operating conditions.  
   - Arrange service to check coolant flow to the hydraulic cooler and filter condition.  

3. **Stop** – Critical temperature reached.  
   - Hydraulic power will be disabled and a red **Stop** alert displayed.  
   - Shut down the machine, wait for temperature to fall below the safe limit, and have the hydraulic system inspected.  

---  

## PROCEDURE P004: Hydraulic Filter Differential Pressure (hydraulic.filter_dp)  

**Component:** Hydraulic pump  
**Limits Reference:** `maintenance/sensor_limits.yaml#filter_dp` (forecast enabled)  

1. **Caution** – Differential pressure rising, indicating filter loading.  
   - Continue operation but avoid prolonged high‑load cycles.  

2. **Service Soon** – Differential pressure exceeds the caution limit.  
   - Log the reading, schedule filter replacement at the next maintenance window.  

3. **Stop** – Differential pressure at critical level.  
   - Hydraulic system will be automatically shut down.  
   - Do not restart until the filter has been replaced and the system flushed.  

---  

## PROCEDURE P005: Engine Air‑Filter Restriction (engine.air_filter_restriction)  

**Component:** Engine  
**Limits Reference:** `maintenance/sensor_limits.yaml#air_restriction` (forecast enabled)  

1. **Caution** – Restriction indicator rising.  
   - Reduce engine load, avoid high RPM operation.  

2. **Service Soon** – Restriction exceeds caution threshold.  
   - Stop the machine, inspect the air‑filter housing for debris.  
   - Replace or clean the air filter before the next shift.  

3. **Stop** – Critical restriction reached.  
   - Engine power will be limited; a red **Stop** alert appears.  
   - Shut down the engine, replace the air filter, and verify sensor reset.  

---  

## PROCEDURE P006: DPF Soot Load Percentage (dpf.soot_load_pct)  

**Component:** Diesel Particulate Filter (DPF)  
**Limits Reference:** `maintenance/sensor_limits.yaml#dpf_soot` (forecast enabled)  

1. **Caution** – Soot load approaching regeneration trigger.  
   - Continue normal operation; the controller may start a passive regeneration automatically.  

2. **Service Soon** – Soot load exceeds the caution limit.  
   - Initiate an active regeneration if the machine control permits.  
   - If regeneration fails, schedule DPF cleaning or replacement.  

3. **Stop** – Soot load at critical level; regeneration not possible.  
   - Engine power will be limited and a red **Stop** alert displayed.  
   - Shut down the machine, perform a forced regeneration or DPF service before further use.  

---  

## PROCEDURE P007: Transmission Oil Temperature (transmission.oil_temp)  

**Component:** Transmission  
**Limits Reference:** `maintenance/sensor_limits.yaml#transmission_temp` (forecast enabled)  

1. **Caution** – Temperature rising toward limit.  
   - Reduce load, avoid rapid gear changes.  

2. **Service Soon** – Temperature exceeds caution threshold.  
   - Stop the machine, allow transmission to cool for at least 3 minutes.  
   - Record temperature and operating conditions.  
   - Arrange service to check transmission cooler and oil level.  

3. **Stop** – Critical temperature reached.  
   - Transmission will be locked out; red **Stop** alert shown.  
   - Shut down, wait for cooling, and have the transmission inspected before restart.  

---  

## PROCEDURE P008: Brakes Temperature (brakes.temp)  

**Component:** Brakes  
**Limits Reference:** `maintenance/sensor_limits.yaml#brake_temp`  

1. **Caution** – Brake temperature approaching limit.  
   - Use lighter braking, allow brakes to cool between cycles.  

2. **Service Soon** – Temperature exceeds caution threshold.  
   - Stop the loader, let brakes cool for at least 5 minutes.  
   - Inspect brake pads and discs for glazing or wear.  

3. **Stop** – Critical brake temperature.  
   - Brake system will be disabled; red **Stop** alert displayed.  
   - Do not restart until brakes have been inspected, cooled, and any damaged components replaced.  

---  

## PROCEDURE P009: Tyre Pressure (tyre.pressure_kpa)  

**Component:** Tyres  
**Limits Reference:** `maintenance/sensor_limits.yaml#tyre_pressure_loader` (forecast enabled)  

1. **Caution** – Pressure deviating from nominal range.  
   - Verify load distribution, avoid high‑speed travel.  

2. **Service Soon** – Pressure outside the caution band.  
   - Stop, check tyre pressure with a calibrated gauge.  
   - Inflate or deflate to the manufacturer‑specified pressure.  

3. **Stop** – Pressure at critical low or high limit.  
   - Loader may inhibit movement; red **Stop** alert shown.  
   - Do not operate until tyre pressure is corrected and the sensor is verified.  

---  

## PROCEDURE P010: Tyre Temperature (tyre.temp)  

**Component:** Tyres  
**Limits Reference:** `maintenance/sensor_limits.yaml#tyre_temp`  

1. **Caution** – Tyre temperature rising rapidly (e.g., after prolonged operation on hard surfaces).  
   - Reduce speed, allow tyres to cool.  

2. **Service Soon** – Temperature exceeds caution limit.  
   - Park the loader, let tyres cool for at least 10 minutes.  
   - Inspect for abnormal wear or damage.  

3. **Stop** – Critical tyre temperature.  
   - Loader may restrict movement; red **Stop** alert displayed.  
   - Do not resume operation until tyres are inspected and cooled.  

---  

## PROCEDURE P011: Water in Fuel (fuel.water_in_fuel)  

**Component:** Engine fuel system  
**Limits Reference:** `maintenance/sensor_limits.yaml#wif`  

1. **Caution** – Water content rising but still below critical.  
   - Continue operation, but plan fuel filter change at the next service.  

2. **Service Soon** – Water level exceeds caution threshold.  
   - Stop the engine, drain the fuel tank, replace fuel filter, and refill with clean fuel.  

3. **Stop** – Water level at critical limit.  
   - Engine power will be limited; red **Stop** alert shown.  
   - Shut down, perform complete fuel system purge, and verify sensor reset before restart.  

---  

## PROCEDURE P012: Electrical System Voltage (electrical.system_voltage)  

**Component:** Electrical system  
**Limits Reference:** `maintenance/sensor_limits.yaml#sys_voltage`  

1. **Caution** – Voltage dropping toward low‑voltage limit.  
   - Reduce electrical load (e.g., turn off non‑essential accessories).  

2. **Service Soon** – Voltage below caution threshold.  
   - Stop the loader, check battery connections and charge level.  
   - Arrange alternator or battery service as needed.  

3. **Stop** – Voltage at critical low or high limit.  
   - Machine will inhibit operation; red **Stop** alert displayed.  
   - Shut down, resolve the electrical fault, and verify voltage before restarting.  

---  

## Forecast Alerts  

Sensors marked with **forecast: true** (coolant temperature, hydraulic oil temperature, hydraulic filter differential pressure, air‑filter restriction, DPF soot load, transmission oil temperature, tyre pressure) can generate **forecast** alerts. These alerts predict that the parameter will exceed a limit within the next operating cycle based on trend analysis.  

- **Operator Action:** Treat a forecast alert as a **Caution** level. Reduce load and monitor the parameter closely.  
- **Service Action:** Log the forecast condition and schedule preventive service before the predicted exceedance occurs.  

> **WARNING:** Ignoring forecast alerts can lead to rapid escalation to **Service Soon** or **Stop** conditions, increasing downtime and repair cost.  

---  

### Summary Table  

| Sensor ID | Component | Forecast? | Caution Action | Service‑Soon Action | Stop Action |
|-----------|-----------|-----------|----------------|---------------------|-------------|
| engine.coolant_temp | Cooling | Yes | Lighten load | Idle, log, call service | Power‑limit, shut down |
| engine.oil_pressure | Engine | No | Reduce RPM | Check oil, schedule inspection | Power‑limit, shut down |
| hydraulic.oil_temp | Hydraulic pump | Yes | Reduce demand | Idle, log, check cooler | Power‑limit, shut down |
| hydraulic.filter_dp | Hydraulic pump | Yes | Avoid prolonged load | Log, replace filter soon | System shut‑off |
| engine.air_filter_restriction | Engine | Yes | Lighten load | Stop, replace/clean filter | Power‑limit, shut down |
| dpf.soot_load_pct | DPF | Yes | Monitor, allow passive regen | Active regen or service | Power‑limit, shut down |
| transmission.oil_temp | Transmission | Yes | Lighten load | Cool, log, check cooler | Lockout, shut down |
| brakes.temp | Brakes | No | Light braking | Cool, inspect pads | Brake lockout |
| tyre.pressure_kpa | Tyres | Yes | Verify load, avoid speed | Inflate/deflate, log | Movement inhibition |
| tyre.temp | Tyres | No | Reduce speed | Cool, inspect | Movement inhibition |
| fuel.water_in_fuel | Fuel system | No | Plan filter change | Drain, replace filter | Engine power limit |
| electrical.system_voltage | Electrical | No | Reduce accessories | Check battery/alternator | System lockout |

---  

**End of Section – Sensor Limits and Alert Responses**
