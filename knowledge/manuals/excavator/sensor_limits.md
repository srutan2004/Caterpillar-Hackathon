---
machine_class: excavator
section: sensor_limits
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.864061+00:00'
---

# Sensor Limits and Alert Responses  
*Section: sensor_limits*  

This section explains the meaning of each maintenance‑alert tier, the required operator actions, and the service‑provider response for all on‑board sensors listed in the **maintenance_sensors** table for the excavator (both diesel and electric variants).  

---  

## 1. Alert Tier Overview  

| Tier | Definition | Typical Operator Action | Service‑Provider Response |
|------|------------|--------------------------|---------------------------|
| **Monitor** | Sensor reading is within normal operating range but approaching a predefined limit. | Continue normal operation, note the reading on the daily log, and re‑check at the next scheduled interval. | No immediate service required; monitor trend. |
| **Service Soon** | Reading has crossed the first warning threshold and indicates a developing condition that could affect performance or durability if left unattended. | Reduce load where possible, complete the current task, and schedule a service stop at the earliest convenient time. | Technician will plan a preventive inspection and replace or adjust the affected component before the next shift. |
| **Stop** | Reading exceeds the critical limit. Continuing operation could cause damage, safety hazard, or regulatory non‑compliance. | Immediately stop the machine, secure the work area, and notify the supervisor. Do not restart until the fault has been cleared by qualified service personnel. | Technician performs corrective repair, resets the sensor, and verifies that the reading returns to the **Monitor** range before returning the machine to service. |

> **NOTE:** Some sensors also provide *forecast* alerts. These are predictive warnings based on trend analysis (e.g., temperature rise rate). Forecast alerts are always presented as **Service Soon** tier messages, giving the operator extra lead time to intervene before a hard limit is reached.  

---  

## 2. Sensor‑Specific Alert Information  

The following subsections list each sensor, the component it monitors, and the meaning of its alert tiers. The **limits_ref** column points to the detailed limit definitions in the master file *maintenance/sensor_limits.yaml* (not reproduced here).  

| Sensor ID | Component | Forecast? |
|-----------|-----------|-----------|
| `engine.coolant_temp` | cooling | ✅ |
| `engine.oil_pressure` | engine (normalised by `engine.rpm`) | – |
| `hydraulic.oil_temp` | hydraulic pump | ✅ |
| `hydraulic.pressure_ripple` | hydraulic pump | ✅ |
| `hydraulic.filter_dp` | hydraulic pump | ✅ |
| `engine.air_filter_restriction` | engine | ✅ |
| `dpf.soot_load_pct` | DPF | ✅ |
| `fuel.water_in_fuel` | engine | – |
| `electrical.system_voltage` | electrical | – |
| `swing.vibration_rms` | swing drive | ✅ |
| `undercarriage.track_tension_mm` | undercarriage | – |
| `battery.cell_dv_mv` *(electric variant)* | battery | ✅ |
| `battery.pack_temp` *(electric variant)* | battery | ✅ |
| `battery.insulation_kohm` *(electric variant)* | electrical | – |

---  

## 3. Procedures  

Each procedure below follows the same structure:  

1. **Identify the alert** (tier and sensor).  
2. **Operator actions** (what to do on‑site).  
3. **Service‑provider actions** (what the maintenance team must do).  

> **WARNING:** Ignoring a **Stop** alert can result in catastrophic component failure, loss of machine availability, or personal injury.  

---  

### PROCEDURE P01: Engine Coolant Temperature – `engine.coolant_temp`  

1. **Alert detection** – The display shows **Monitor**, **Service Soon**, or **Stop** for coolant temperature.  
2. **Operator actions**  
   - **Monitor**: Continue operation; record temperature at the end of the shift.  
   - **Service Soon**: Reduce engine load (e.g., lower swing speed, avoid full‑boom lift), check radiator fan operation, and plan a service stop as soon as possible.  
   - **Stop**: Immediately shut down the engine, allow it to cool, and notify the supervisor. Do not restart until the coolant system has been inspected.  
3. **Service‑provider actions**  
   - Inspect coolant level, concentration, and circulation pump.  
   - Verify thermostat operation and radiator cleanliness.  
   - Replace coolant if contamination is detected.  

---  

### PROCEDURE P02: Engine Oil Pressure – `engine.oil_pressure`  

1. **Alert detection** – Pressure reading is normalised by engine RPM; alerts appear as **Monitor**, **Service Soon**, or **Stop**.  
2. **Operator actions**  
   - **Monitor**: No action required; log the pressure value.  
   - **Service Soon**: Reduce engine RPM where possible, avoid high‑load cycles, and schedule a service stop before the next shift.  
   - **Stop**: Stop the machine immediately, engage the parking brake, and inform maintenance. Do not restart until oil pressure is restored.  
3. **Service‑provider actions**  
   - Check oil level, filter condition, and oil pump.  
   - Replace oil filter and top‑up oil if needed.  
   - Inspect for leaks in the oil circuit.  

---  

### PROCEDURE P03: Hydraulic Oil Temperature – `hydraulic.oil_temp`  

1. **Alert detection** – Forecast capability predicts temperature trend; alerts are **Service Soon** (forecast) or **Stop** (hard limit).  
2. **Operator actions**  
   - **Monitor**: Continue operation; note temperature trend.  
   - **Service Soon (forecast)**: Reduce hydraulic demand (lower swing speed, avoid rapid pump cycling), and arrange a service stop at the next convenient opportunity.  
   - **Stop**: Shut down the machine, allow the hydraulic system to cool, and contact service.  
3. **Service‑provider actions**  
   - Verify hydraulic oil level and condition.  
   - Clean or replace the hydraulic oil filter.  
   - Check pump cooling passages for blockage.  

---  

### PROCEDURE P04: Hydraulic Pressure Ripple – `hydraulic.pressure_ripple`  

1. **Alert detection** – Ripple exceeds normal limits; forecast alerts give early warning.  
2. **Operator actions**  
   - **Monitor**: No immediate action.  
   - **Service Soon (forecast)**: Avoid rapid pressure changes; operate at moderate swing speeds. Schedule inspection.  
   - **Stop**: Power down, secure the machine, and call service.  
3. **Service‑provider actions**  
   - Inspect pump and relief valve for wear or blockage.  
   - Replace pressure‑ripple dampening components if required.  

---  

### PROCEDURE P05: Hydraulic Filter Differential Pressure – `hydraulic.filter_dp`  

1. **Alert detection** – Differential pressure across the filter indicates clogging.  
2. **Operator actions**  
   - **Monitor**: Record value; no action.  
   - **Service Soon**: Reduce hydraulic load, plan filter change at the next maintenance window.  
   - **Stop**: Shut down, do not restart until filter is replaced.  
3. **Service‑provider actions**  
   - Replace hydraulic filter.  
   - Flush the hydraulic circuit if pressure remains high after filter change.  

---  

### PROCEDURE P06: Engine Air‑Filter Restriction – `engine.air_filter_restriction`  

1. **Alert detection** – Forecast alerts warn of increasing restriction.  
2. **Operator actions**  
   - **Monitor**: Continue; note any loss of power.  
   - **Service Soon (forecast)**: Reduce engine load, avoid dusty conditions if possible, and schedule filter inspection.  
   - **Stop**: Stop the machine, inspect air‑filter housing, and contact service.  
3. **Service‑provider actions**  
   - Clean or replace the air filter element.  
   - Inspect intake ducts for debris.  

---  

### PROCEDURE P07: DPF Soot Load – `dpf.soot_load_pct`  

1. **Alert detection** – Percentage of soot stored in the diesel particulate filter.  
2. **Operator actions**  
   - **Monitor**: No action; log percentage.  
   - **Service Soon**: Initiate a regeneration cycle if the machine supports it, or plan a service stop for forced regeneration.  
   - **Stop**: Cease operation; the filter is blocked. Service must perform a full regeneration or replace the DPF.  
3. **Service‑provider actions**  
   - Run a controlled regeneration according to the service manual.  
   - Replace DPF if regeneration fails.  

---  

### PROCEDURE P08: Fuel Water in Fuel – `fuel.water_in_fuel`  

1. **Alert detection** – Water content exceeds the permissible limit.  
2. **Operator actions**  
   - **Monitor**: No immediate action.  
   - **Service Soon**: Drain the fuel tank and refill with clean fuel; schedule tank cleaning.  
   - **Stop**: Stop the machine; do not restart until fuel is drained and the tank is dried.  
3. **Service‑provider actions**  
   - Drain and purge the fuel system.  
   - Replace fuel filters and water‑separator elements.  

---  

### PROCEDURE P09: Electrical System Voltage – `electrical.system_voltage`  

1. **Alert detection** – Voltage falls outside the normal band.  
2. **Operator actions**  
   - **Monitor**: Note voltage; continue operation.  
   - **Service Soon**: Verify battery connections, reduce electrical load (e.g., turn off non‑essential accessories).  
   - **Stop**: Shut down the machine; do not restart until voltage is restored to normal.  
3. **Service‑provider actions**  
   - Test alternator/charging system.  
   - Inspect wiring harnesses for corrosion or loose terminals.  

---  

### PROCEDURE P10: Swing Drive Vibration – `swing.vibration_rms`  

1. **Alert detection** – RMS vibration exceeds limits; forecast alerts predict worsening vibration.  
2. **Operator actions**  
   - **Monitor**: Continue operation; log RMS value.  
   - **Service Soon (forecast)**: Reduce swing speed, avoid abrupt direction changes, and arrange inspection.  
   - **Stop**: Stop the machine, secure the swing, and contact service.  
3. **Service‑provider actions**  
   - Inspect swing motor bearings and couplings.  
   - Balance swing components if imbalance is detected.  

---  

### PROCEDURE P11: Undercarriage Track Tension – `undercarriage.track_tension_mm`  

1. **Alert detection** – Track tension measured in millimetres deviates from the set range.  
2. **Operator actions**  
   - **Monitor**: No action; record tension.  
   - **Service Soon**: Reduce ground pressure (lower machine weight on tracks) and schedule tension adjustment.  
   - **Stop**: Stop the machine; do not move until tension is corrected.  
3. **Service‑provider actions**  
   - Adjust track tension using the undercarriage adjustment bolts.  
   - Inspect track rollers and idlers for wear.  

---  

### PROCEDURE P12: Battery Cell Voltage Difference – `battery.cell_dv_mv` *(electric variant)*  

1. **Alert detection** – Cell‑to‑cell voltage difference exceeds the forecast limit.  
2. **Operator actions**  
   - **Monitor**: Continue operation; note the value.  
   - **Service Soon (forecast)**: Reduce power demand (lower swing speed, avoid rapid acceleration) and arrange battery health check.  
   - **Stop**: Shut down; contact service before further use.  
3. **Service‑provider actions**  
   - Perform cell balancing or replace defective cells.  

---  

### PROCEDURE P13: Battery Pack Temperature – `battery.pack_temp` *(electric variant)*  

1. **Alert detection** – Pack temperature rises toward the forecast limit.  
2. **Operator actions**  
   - **Monitor**: No action; log temperature.  
   - **Service Soon (forecast)**: Reduce load, allow cooling time, and schedule pack inspection.  
   - **Stop**: Power down the machine; do not restart until temperature is within normal range.  
3. **Service‑provider actions**  
   - Inspect cooling system (fans, liquid circuit).  
   - Check for cell degradation or thermal runaway signs.  

---  

### PROCEDURE P14: Battery Insulation Resistance – `battery.insulation_kohm` *(electric variant)*  

1. **Alert detection** – Insulation resistance falls below the safe threshold.  
2. **Operator actions**  
   - **Monitor**: Record value; continue operation if within safe range.  
   - **Service Soon**: Reduce high‑voltage usage, avoid operating in wet conditions, and schedule insulation test.  
   - **Stop**: Immediately stop; risk of electrical leakage.  
3. **Service‑provider actions**  
   - Perform insulation resistance test with a megohmmeter.  
   - Repair or replace damaged wiring or connectors.  

---  

## 4. General Monitoring and Reporting Guidelines  

| Item | Frequency | Responsibility |
|------|-----------|----------------|
| Daily sensor‑status check (all tiers) | Start of shift | Operator |
| Log of **Service Soon** alerts | Each occurrence | Operator |
| Maintenance request generation | As soon as a **Service Soon** occurs or immediately for **Stop** | Operator |
| Forecast trend review (temperature, vibration, etc.) | Periodically or after any **Service Soon** forecast | Operator |
| Post‑service verification | After any corrective action | Service technician |

> **WARNING:** Failure to record and act on a **Service Soon** forecast can allow the condition to progress to a **Stop** tier, resulting in unplanned downtime.  

---  

## 5. Summary  

- **Monitor** – Observe, log, and continue operation.  
- **Service Soon** – Reduce load, plan a service stop, and treat forecast alerts as early warnings.  
- **Stop** – Immediate shutdown, secure the machine, and await qualified service.  

By adhering to these procedures, operators ensure safe operation, prolong component life, and minimise unexpected downtime.
