---
machine_class: excavator
section: fluids
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.856519+00:00'
---

# Fluids and Capacities (Fluids)

This section describes the energy‑storage capacities of the excavator, the specifications for the fluids (or electrical energy) it uses, and the step‑by‑step procedures for refuelling a diesel‑powered unit or charging an electric‑powered unit. All numerical values are taken directly from the **SPEC VALUES** table and must not be altered.

---

## 1. Energy‑Storage Summary

| Machine Type | Energy Storage | Nominal Capacity | Usable Capacity* |
|--------------|----------------|------------------|------------------|
| Diesel‑powered excavator | Fuel tank | **400 L** | N/A |
| Electric‑powered excavator | Battery pack | **300 kWh** | **0.95 × 300 kWh** |

\*Usable capacity is the portion of the total battery energy that can be drawn before the system forces a shutdown (0.95 of the nominal 300 kWh).

---

## 2. Fluid / Energy Specifications

| Parameter | Specification | Remarks |
|-----------|---------------|---------|
| **Fuel type** | Diesel, ISO grade 2 or higher | Must meet local emissions standards |
| **Fuel temperature range** | Within ambient limits | Allow fuel to reach ambient temperature before refuelling |
| **Battery chemistry** | Lithium‑ion (generic) | Follow manufacturer‑provided handling guidelines |
| **Battery voltage** | Nominal DC (as defined by the system) | Do not exceed rated voltage during charging |
| **Charge efficiency** | **0.93** | Energy loss is accounted for in charging time calculations |
| **Maximum charge power** | **150 kW** (DC fast) <br> **44 kW** (AC site) | Select charger type according to availability |
| **Charge taper start** | **SOC = 0.8** (state‑of‑charge) | After this point, power is reduced to protect the battery |
| **Power fraction at full SOC** | **0.25** (fraction of max power) | Final portion of charge proceeds at reduced power |

---

## 3. Procedures

> **NOTE:** Before performing any of the procedures below, ensure the machine is on a level surface, the parking brake is engaged, and all personnel are wearing appropriate personal protective equipment (PPE).

### PROCEDURE 001: Refuel Diesel‑Powered Excavator

1. **Prepare the site**  
   - Verify that a fire‑extinguishing device (Class B) is within reach.  
   - Shut off the engine and allow the exhaust system to cool.  

2. **Open the fuel tank cap**  
   - Locate the fuel tank filler neck on the right‑hand side of the chassis.  
   - Turn the cap counter‑clockwise until it releases.  

3. **Connect the refuelling hose**  
   - Attach a clean, approved diesel hose to the filler neck.  
   - Ensure the hose is securely clamped to prevent leakage.  

4. **Begin refuelling**  
   - Start the pump. The **refuel rate** is **60 L /min**.  
   - Monitor the flow meter; stop the pump when the tank reaches full capacity.  

5. **Terminate the flow**  
   - Close the pump valve before disconnecting the hose to avoid spillage.  

6. **Secure the tank**  
   - Remove the hose, wipe any drips from the filler neck, and replace the cap, turning it clockwise until it clicks.  

7. **Post‑refuel checks**  
   - Inspect for fuel leaks around the filler neck.  
   - Record the fuel quantity added in the equipment log.  

> **WARNING:** Never smoke or use open flames within the immediate vicinity of the refuelling area. Diesel vapour is highly flammable.

---

### PROCEDURE 002: Charge Electric‑Powered Excavator (AC Site Charger)

1. **Verify charger compatibility**  
   - Confirm that the charger is rated for **44 kW** AC output and supports the excavator’s battery system.  

2. **Connect the charging cable**  
   - Align the charger’s plug with the vehicle’s charging inlet (located on the rear left side).  
   - Engage the latch and verify a firm connection.  

3. **Initiate charging**  
   - Power on the charger and select the **AC site** mode.  
   - The charger will deliver up to **44 kW** until the battery reaches the defined charge‑taper start point.  

4. **Monitor charge taper**  
   - When the battery SOC reaches **0.8**, the charger automatically reduces power to **0.25 × 44 kW**.  
   - Continue charging until the SOC reaches the floor reference defined by the system.  

5. **Terminate charging**  
   - Once the desired SOC is reached, press the “Stop” button on the charger.  
   - Disconnect the cable, securing the connector in its protective cover.  

6. **Record the session**  
   - Log the start time, end time, total energy delivered, and final SOC in the maintenance record.  

> **WARNING:** Do not attempt to charge the battery if the inlet is wet, damaged, or if the charger displays a fault code. Improper connection can cause electric shock or battery damage.

---

### PROCEDURE 003: Charge Electric‑Powered Excavator (DC Fast Charger)

1. **Select a DC fast‑charging station**  
   - The station must be capable of delivering **150 kW** DC power.  

2. **Prepare the vehicle**  
   - Ensure the excavator is parked with the charging inlet accessible.  
   - Activate the vehicle’s “Charging Ready” mode via the operator console.  

3. **Connect the DC cable**  
   - Align the DC plug with the inlet, engage the locking mechanism, and confirm the indicator light turns green.  

4. **Start the fast‑charge cycle**  
   - The charger will supply up to **150 kW** until the battery reaches the defined charge‑taper start point.  

5. **Observe charge taper**  
   - At **SOC = 0.8**, power is reduced to **0.25 × 150 kW**.  
   - Continue charging until the SOC floor reference is reached.  

6. **Complete the charge**  
   - When charging is finished, the charger will automatically stop and the indicator will flash amber.  
   - Release the lock, withdraw the cable, and store it in its cradle.  

7. **Log the operation**  
   - Record start/end times, total energy transferred, and final SOC.  

> **WARNING:** DC fast charging generates high currents; keep the area clear of conductive objects and maintain a safe clearance around the connector.

---

### PROCEDURE 004: Verify Fluid / Energy Levels

1. **Access the instrument panel**  
   - Turn the ignition to the “ON” position.  

2. **Read the fuel gauge (diesel model)**  
   - The digital display shows fuel volume in litres. Verify that the reading does not exceed the tank capacity.  

3. **Read the battery SOC (electric model)**  
   - The SOC bar indicates percentage. Ensure the value is at or above the SOC floor reference before operation.  

4. **Perform a visual inspection**  
   - Check for leaks around the fuel tank or battery enclosure.  

5. **Document**  
   - Enter the current level and any observations in the daily log.  

> **WARNING:** Never open the battery enclosure while the system is energized. De‑energize the machine before any internal inspection.

---

## 4. Maintenance Intervals (Reference Only)

| Item | Recommended Interval | Action |
|------|----------------------|--------|
| Fuel filter (diesel) | As specified by the manufacturer | Replace |
| Battery health check (electric) | As specified by the manufacturer | Perform diagnostic scan |
| Charging connector inspection | Periodically | Clean, tighten, and test continuity |

*Intervals are guidelines; adjust based on operating conditions and manufacturer recommendations.*

---

## 5. Safety Summary

| Hazard | Mitigation |
|--------|------------|
| Fuel spillage | Use drip trays, immediate cleanup with approved absorbent |
| Battery over‑temperature | Monitor temperature sensors; abort charge if temperature exceeds safe limits |
| Electrical shock | Verify lock‑out/tag‑out before accessing high‑voltage components |
| Fire | Keep a Class B extinguisher readily available during refuelling |

---

**End of Fluids and Capacities (Fluids) Section**. All procedures must be followed exactly as written to ensure safe and efficient operation of the excavator.
