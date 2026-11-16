---
machine_class: adt
section: fluids
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.819208+00:00'
---

# Fluids and Capacities (Fluids)

This section describes the fuel system of the articulated dump truck, the capacities involved, the specifications for the fuel, and the step‑by‑step procedure for refuelling. All numbers are taken directly from the **SPEC VALUES** table and must not be altered.

---

## 1. Fuel System Overview

| Item | Description |
|------|-------------|
| **Fuel Type** | Diesel fuel meeting the specifications in Section 2. |
| **Fuel Tank Capacity** | **400 L** (as defined in `adt_30t.energy.tank_l`). |
| **Maximum Refuel Flow Rate** | **80 L/min** (as defined in `adt_30t.energy.refuel_rate_lpm`). |
| **Location of Tank Fill Port** | Rear‑right side of the chassis, protected by a hinged cover. |
| **Ventilation** | Automatic vent valve with over‑pressure relief. |
| **Fuel Filter** | Inline, replaceable cartridge, service interval listed in the Maintenance Schedule. |

The fuel tank is a closed, welded steel container designed to meet ISO 1217 standards for durability and leak‑free operation. The tank is equipped with a level sensor that feeds a digital read‑out on the operator console.

---

## 2. Fuel Specification

| Parameter | Required Specification |
|-----------|------------------------|
| **Cetane Number** | ≥ 50 |
| **Sulphur Content** | ≤ ppm |
| **Water Content** | ≤ % by volume |
| **Temperature Range for Storage** | – °C to + °C |
| **Approved Additives** | Only those listed in the OEM‑approved additive guide. |

> **NOTE:** Using fuel that does not meet these specifications can cause injector fouling, reduced power output, and may void the warranty.

---

## 3. Refuel Procedure

The following procedures must be performed by qualified personnel only. Always wear appropriate personal protective equipment (PPE) – safety glasses, chemical‑resistant gloves, and flame‑resistant clothing.

### PROCEDURE REF001: Prepare for Refuelling

1. **Park the Vehicle**  
   - Bring the truck to a level surface.  
   - Engage the parking brake and set the transmission to neutral.  
   - Turn off the engine and wait for residual pressure to dissipate.

2. **Ground the Vehicle**  
   - Connect a grounding strap from the chassis to a certified earth point to prevent static discharge.

3. **Open the Fuel Fill Cover**  
   - Release the latch on the rear‑right side and swing the cover open.  
   - Inspect the area for sparks, open flames, or smoking cigarettes.  

> **WARNING:** Do **not** start the engine or operate any electrical equipment while refuelling.  

### PROCEDURE REF002: Connect the Refuelling Hose

1. Remove the protective cap from the fuel fill port.  
2. Attach the refuelling hose securely, ensuring the coupling clicks into place.  
3. Verify that the hose is rated for a minimum flow rate of **80 L/min** (the truck’s maximum refuel rate).  

### PROCEDURE REF003: Refuel the Tank

| Step | Action | Target |
|------|--------|--------|
| 3.1 | Open the fuel pump valve on the dispenser. | – |
| 3.2 | Begin fuel flow. | Observe the tank level indicator. |
| 3.3 | Monitor the flow rate. | **Do not exceed 80 L/min**. |
| 3.4 | Stop the pump when the tank reaches **400 L** or when the on‑board level sensor indicates “Full”. | – |
| 3.5 | Close the pump valve and disconnect the hose. | – |
| 3.6 | Replace the fuel fill cap and secure the cover. | – |

> **WARNING:** Over‑filling can cause fuel spillage, fire hazard, and damage to the venting system.  

### PROCEDURE REF004: Post‑Refuel Checks

1. **Check for Leaks** – Visually inspect the fill area for any fuel drips.  
2. **Ventilation** – Ensure the vent valve is operating freely; a blocked vent can cause pressure buildup.  
3. **Record the Refuel** – Log the quantity of fuel added, the time, and the operator’s name in the vehicle’s fuel log.  
4. **Reset the Fuel Level Sensor** (if required by the electronic system) by following the steps in the “Electronic Diagnostics” chapter.  

---

## 4. Additional Fluid Capacities (Optional)

While the primary fluid for this articulated dump truck is diesel fuel, the vehicle also contains other fluids that must be monitored. The capacities for these fluids are not listed in the current SPEC VALUES, so the procedures below describe the actions without numeric thresholds.

### PROCEDURE FLD001: Check Hydraulic Fluid Level

1. Locate the hydraulic reservoir dip‑stick on the left side of the cab.  
2. Clean the dip‑stick, re‑insert it fully, then withdraw to read the level.  
3. If the level is below the “MIN” mark, add the specified hydraulic oil until the “MAX” mark is reached.  

### PROCEDURE FLD002: Inspect Engine Coolant

1. Open the coolant reservoir cap (engine must be cold).  
2. Verify that the coolant level is between the “LOW” and “HIGH” marks.  
3. Top up with the approved coolant mixture if necessary.  

> **WARNING:** Never open hot coolant reservoirs – risk of scalding.  

---

## 5. Maintenance Recommendations

| Fluid | Recommended Service Interval* | Remarks |
|-------|-------------------------------|---------|
| Diesel Fuel Filter | Every **km** or **months** (whichever occurs first) | Replace with a filter meeting OEM specifications. |
| Hydraulic Oil | Every **km** or **months** | Flush and refill with the correct viscosity grade. |
| Engine Coolant | Every **km** or **months** | Use a 50/50 mix of approved antifreeze and distilled water. |

\*Intervals are typical; consult the operator’s maintenance schedule for exact values.

---

## 6. Safety Summary

| Hazard | Mitigation |
|--------|------------|
| Fuel spillage | Use drip pans, keep fire extinguishers nearby, and follow REF001‑REF004. |
| Static discharge | Ground the vehicle before connecting the hose (REF001). |
| Over‑pressurisation of tank vent | Do not block vent; inspect vent regularly (REF004). |
| Contamination of fuel | Use only approved fuel, keep the fill port sealed when not in use. |

---

## 7. Documentation and Records

All refuelling events must be recorded in the **Fuel Logbook** with the following fields:

| Field | Description |
|-------|-------------|
| Date | Calendar date of refuelling. |
| Operator | Name or ID of the person performing the refuel. |
| Quantity Added | Volume in litres (max 400 L). |
| Fuel Supplier | Name of the fuel station or supplier. |
| Remarks | Any observations (e.g., fuel quality, temperature). |

Keeping accurate records assists in troubleshooting, ensures compliance with environmental regulations, and supports warranty claims.

---

*End of Fluids and Capacities (Fluids) section.*
