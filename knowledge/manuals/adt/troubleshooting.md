---
machine_class: adt
section: troubleshooting
procedure_ids:
- HYD-TEMP-02
- COOL-RAD-02
- COOL-TEMP-01
- ENG-OILP-01
- ENG-AIR-01
- ENG-WIF-01
- DPF-SOOT-01
- ELE-ALT-01
- TYR-LEAK-01
- TRN-TEMP-01
- BRK-TEMP-01
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.853690+00:00'
---

## Troubleshooting by Fault Code  

The following procedures are organized by fault‑code. Each procedure lists the checks that must be performed, the corrective actions that may be required, and the criteria for determining whether the machine can be returned to service safely. All actions must be carried out by qualified personnel wearing the appropriate personal protective equipment (PPE).

---  

### PROCEDURE HYD‑TEMP‑02: Hydraulic‑System Over‑Temperature  

> **WARNING:**  Hydraulic fluid at elevated temperature can cause burns and may degrade system seals. Stop the machine and allow the system to cool before attempting any disassembly.  

1. **Verify fault indication** – Confirm that the hydraulic‑temperature warning lamp is illuminated and that the on‑board display shows a temperature above the normal operating range.  
2. **Inspect coolant level** – Open the hydraulic‑fluid reservoir and check that the fluid level is within the sight‑glass marks. Top up with the specified hydraulic fluid if low.  
3. **Check for external heat sources** – Ensure that the radiator, cooling fans, and hydraulic‑oil cooler are free of debris and that airflow is not obstructed.  
4. **Examine hoses and fittings** – Look for signs of leakage, bulging, or chafing that could cause loss of pressure and excess heat generation.  
5. **Measure fluid temperature** – Using a calibrated infrared thermometer, record the temperature at the hydraulic‑oil cooler outlet. Compare with the manufacturer’s normal range (see the service catalogue).  
6. **Cool‑down procedure** – If temperature exceeds the safe limit, park the vehicle, engage the parking brake, and allow the system to cool for at least 15 minutes before restarting.  
7. **Reset fault** – After the system has cooled and any deficiencies have been corrected, clear the fault code from the diagnostic console. Observe the machine for a full operating cycle to verify that the temperature remains within limits.  

*If the temperature rises again after the reset, proceed to a detailed hydraulic‑system inspection or contact service support.*  

---  

### PROCEDURE COOL‑RAD‑02: Radiator Coolant Low  

> **WARNING:** Operating the machine with insufficient coolant can cause engine overheating and severe damage.  

1. **Confirm fault** – The coolant‑level sensor must be active and the low‑coolant warning displayed.  
2. **Inspect coolant reservoir** – Open the radiator cap only when the engine is cool. Verify that the coolant level is between the “MIN” and “MAX” marks.  
3. **Check for leaks** – Examine the radiator, hoses, water pump, and coolant‑tank for external leaks, wet spots, or corrosion.  
4. **Top‑up coolant** – If the level is low, add the specified coolant‑mix to the correct level. Do not over‑fill.  
5. **Bleed the cooling system** – Remove any trapped air by opening the bleed valve (if equipped) and running the engine at idle until the coolant circulates steadily and no air bubbles are visible in the reservoir.  
6. **Re‑inspect** – After the top‑up, re‑check the sensor reading. If the warning persists, verify the sensor wiring and connector for damage.  

*If the coolant level repeatedly drops, a leak in the cooling circuit must be repaired before further operation.*  

---  

### PROCEDURE COOL‑TEMP‑01: Engine Coolant Temperature High  

> **WARNING:** Continuing to operate with high coolant temperature can lead to engine seizure.  

1. **Acknowledge the alarm** – The temperature gauge must indicate a value above the normal operating range.  
2. **Stop the machine** – Bring the vehicle to a safe stop, engage the parking brake, and allow the engine to idle for a minimum of 5 minutes.  
3. **Inspect radiator and fan operation** – Verify that the radiator fan(s) engage automatically when the temperature rises. Listen for abnormal noises that could indicate a failed fan motor.  
4. **Check coolant flow** – With the engine still warm, open the radiator cap carefully (use a rag) and feel for coolant movement. Lack of flow may indicate a blocked radiator or a failed water pump.  
5. **Examine thermostat** – If the engine cools very slowly, the thermostat may be stuck closed. Replace according to the service manual.  
6. **Verify sensor integrity** – Inspect the coolant‑temperature sensor and its wiring for corrosion or damage. Replace if readings are erratic.  
7. **Clear fault** – After corrective actions, reset the fault code and monitor the temperature during a test run.  

*If temperature spikes continue, a detailed cooling‑system diagnosis (including pressure testing) is required.*  

---  

### PROCEDURE ENG‑OILP‑01: Engine Oil Pressure Low  

> **WARNING:** Low oil pressure can cause rapid engine wear or failure. Do not operate the machine until the condition is resolved.  

1. **Confirm alarm** – The oil‑pressure gauge must read below the minimum safe pressure.  
2. **Check oil level** – Park on level ground, wait for the engine to stop, and check the dip‑stick. The oil must be within the “MIN” and “MAX” marks. Top up with the specified engine oil if necessary.  
3. **Inspect oil filter** – A clogged filter can restrict flow. Remove and inspect the filter element; replace if dirty or blocked.  
4. **Examine oil pump** – Listen for unusual noises from the pump area. Excessive bearing noise may indicate pump wear.  
5. **Look for leaks** – Check the oil pan, valve cover gaskets, and oil lines for external leaks.  
6. **Warm‑up test** – After topping up and any filter change, start the engine and allow it to reach normal operating temperature. Observe the pressure gauge; it should rise into the normal range.  
7. **Reset fault** – Clear the code and perform a short‑duration test run.  

*If pressure remains low after these steps, the oil pump must be removed for inspection or replacement.*  

---  

### PROCEDURE ENG‑AIR‑01: Air Intake Restriction  

> **WARNING:** Operating with a restricted air intake can cause engine over‑temperature and loss of power.  

1. **Identify symptom** – The diagnostic display shows “AIR‑INLET‑RESTRICTION” or a related warning.  
2. **Inspect air filter** – Remove the air‑filter housing and examine the filter element. Replace if it is dirty, damaged, or clogged.  
3. **Check intake ducting** – Ensure that the duct, intake hose, and pre‑cleaner are free of debris, leaves, or ice.  
4. **Verify sensor operation** – The mass‑air‑flow (MAF) sensor or pressure sensor must be clean. Use a sensor‑cleaning solvent if needed, following the manufacturer’s instructions.  
5. **Examine turbocharger (if equipped)** – Look for oil leaks or excessive play in the turbine housing that could affect airflow.  
6. **Reset fault** – After cleaning/replacement, clear the code and run the engine at idle, then under load, to confirm normal airflow readings.  

*If the fault recurs, a deeper inspection of the turbocharger or intake manifold may be required.*  

---  

### PROCEDURE ENG‑WIF‑01: Engine Water‑In‑Fuel (Water in Fuel)  

> **WARNING:** Water in the fuel system can cause severe engine damage. Do not start the engine until the fuel is verified clean.  

1. **Confirm detection** – The fuel‑water sensor indicates contamination.  
2. **Drain fuel tank** – Safely depressurize the fuel system, then pump out all fuel into a suitable container.  
3. **Inspect fuel filter** – Remove the fuel filter and check for water separation. Replace the filter.  
4. **Dry fuel lines** – Blow compressed air through the lines to remove residual moisture.  
5. **Refill with clean fuel** – Use only the specified fuel grade. Add a fuel‑water separator if recommended by the catalogue.  
6. **Run purge cycle** – Start the engine and allow it to run at idle for several minutes, then shut down and re‑inspect the water sensor.  
7. **Clear fault** – Reset the fault code and verify that the sensor remains dry during a test run.  

*If water reappears, investigate external sources such as condensation in the tank or a leaking fuel‑return line.*  

---  

### PROCEDURE DPF‑SOOT‑01: Diesel Particulate Filter – Excess Soot  

> **WARNING:** Excess soot can cause DPF blockage, leading to loss of power and possible engine over‑temperature.  

1. **Acknowledge alert** – The DPF‑monitor indicates “SOOT‑LEVEL‑HIGH”.  
2. **Check regeneration status** – Verify whether an active regeneration is in progress. If not, initiate a forced regeneration according to the service manual.  
3. **Inspect exhaust back‑pressure** – Use a pressure gauge to measure back‑pressure across the DPF. Values above the catalogue limit indicate blockage.  
4. **Examine DPF inlet and outlet** – Ensure that there are no external obstructions (e.g., mud, debris).  
5. **Verify sensor wiring** – The soot‑level sensor and temperature sensors must be securely connected and free of corrosion.  
6. **Complete regeneration** – Allow the forced regeneration to finish fully; monitor temperature and pressure trends.  
7. **Reset fault** – Clear the DPF‑related code and perform a road‑load test to confirm normal exhaust back‑pressure.  

*If soot levels remain high after a successful regeneration, the DPF may require cleaning or replacement.*  

---  

### PROCEDURE ELE‑ALT‑01: Electrical – Alternator Fault  

> **WARNING:** A failed alternator can lead to loss of critical control systems and battery discharge.  

1. **Confirm fault** – The dashboard displays “ALT‑FAULT” and battery voltage drops below the normal range.  
2. **Measure battery voltage** – With the engine off, verify that the battery reads at least the minimum specified voltage.  
3. **Check alternator belt** – Inspect the drive belt for wear, proper tension, and correct routing. Replace or adjust as needed.  
4. **Test alternator output** – With the engine running, measure voltage at the battery terminals. It must be within the specified charging range (see catalogue).  
5. **Inspect wiring and connectors** – Look for loose pins, corrosion, or damaged harnesses between the alternator and the control module.  
6. **Replace alternator** – If output remains below spec after belt and wiring checks, replace the alternator unit.  
7. **Reset fault** – Clear the code and verify stable voltage during a full operating cycle.  

*Do not operate the vehicle if the alternator fault persists, as it may compromise safety‑critical electronics.*  

---  

### PROCEDURE TYR‑LEAK‑01: Tyre Pressure Loss / Leak  

> **WARNING:** Driving with insufficient tyre pressure can cause tyre failure, loss of control, and damage to the axle.  

1. **Identify warning** – The tyre‑pressure monitoring system (TPMS) indicates a low‑pressure condition on one or more tyres.  
2. **Visually inspect tyre** – Look for punctures, cuts, sidewall damage, or objects embedded in the tread.  
3. **Check valve stem** – Ensure the valve core is tight and not damaged. Replace the valve core if leaking.  
4. **Measure pressure** – Using a calibrated tyre‑pressure gauge, record the pressure of each tyre. Compare with the manufacturer‑specified pressure (found in the vehicle data plate).  
5. **Inflate to spec** – Add air to bring each tyre to the correct pressure.  
6. **Re‑scan TPMS** – Reset the TPMS sensor via the diagnostic console and verify that the warning clears.  
7. **Monitor** – After a short test drive, re‑check pressures to ensure no further loss.  

*If pressure continues to drop, the tyre may have a slow leak and should be removed for a thorough inspection or replacement.*  

---  

### PROCEDURE TRN‑TEMP‑01: Transmission Oil Temperature High  

> **WARNING:** Excessive transmission temperature can degrade oil, damage gears, and cause loss of drive.  

1. **Confirm alarm** – The transmission‑temperature gauge exceeds the normal range.  
2. **Stop and allow cooling** – Park the vehicle, engage the parking brake, and let the transmission cool for at least 10 minutes.  
3. **Check fluid level** – With the transmission at operating temperature, verify the fluid level using the dip‑stick (if equipped) or sight‑glass. Top up with the specified transmission fluid if low.  
4. **Inspect cooler** – Ensure the transmission‑oil cooler and associated fans are free of debris and that airflow is unobstructed.  
5. **Examine vent system** – Verify that the transmission vent hose is not blocked, which could trap heat.  
6. **Measure oil temperature** – Use a calibrated temperature probe to confirm that the oil temperature is now within the catalogue limits.  
7. **Reset fault** – Clear the code and perform a short drive, monitoring the temperature gauge for stability.  

*If temperature spikes recur, the cooler may be clogged or the transmission oil may need to be flushed and replaced.*  

---  

### PROCEDURE BRK‑TEMP‑01: Brake System Over‑Temperature  

> **WARNING:** Over‑heated brakes can lead to fade, loss of stopping power, and fire risk.  

1. **Acknowledge warning** – The brake‑temperature indicator or diagnostic message is active.  
2. **Allow brakes to cool** – Stop the vehicle in a safe area, engage the parking brake, and wait until the brake discs feel cool to the touch (approximately 5–10 minutes).  
3. **Inspect brake drums/discs** – Look for discoloration, glazing, or cracks that indicate overheating.  
4. **Check brake fluid level** – Verify that the fluid is within the “MIN” and “MAX” marks in the reservoir. Top up with the specified brake fluid if low.  
5. **Examine cooling vents** – Ensure that any brake‑cooling ducts or fans are not blocked by debris.  
6. **Test brake performance** – After cooling, perform a low‑speed brake test to confirm normal pedal feel and stopping distance.  
7. **Reset fault** – Clear the brake‑temperature code and monitor during a full operating cycle.  

*If the brake‑temperature warning reappears, investigate prolonged downhill operation, excessive load, or a malfunctioning brake‑temperature sensor.*  

---  

**End of Troubleshooting Section**  

All procedures must be documented in the service log, including fault codes, actions taken, parts replaced, and final test results. This ensures traceability and compliance with maintenance standards.
