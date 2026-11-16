---
machine_class: excavator
section: troubleshooting
procedure_ids:
- HYD-PUMP-01
- HYD-FILT-03
- HYD-TEMP-02
- COOL-RAD-02
- COOL-TEMP-01
- ENG-OILP-01
- ENG-AIR-01
- ENG-WIF-01
- DPF-SOOT-01
- ELE-ALT-01
- SWG-VIB-01
- UC-TRK-01
- GET-WEAR-01
- BAT-CELL-01
- BAT-ISO-01
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.867898+00:00'
---

## Troubleshooting by Fault Code  
*All procedures are written for a generic 20‑ton excavator. The steps are ordered to isolate the fault, verify safe conditions, and determine whether operation may continue. Use only the tools and personal‑protective‑equipment (PPE) required for each step.*

---  

### PROCEDURE HYD‑PUMP‑01: Low Hydraulic Pressure  
1. **Verify safety** – Park the machine on level ground, set the parking brake, and engage the engine‑stop switch.  
2. **Check hydraulic fluid level** – Open the hydraulic reservoir cap (use a clean rag) and confirm the fluid is at the “MAX” mark. If low, add the correct hydraulic oil until the level reaches the mark.  
> **WARNING:** Never over‑fill the reservoir; excess fluid can cause pump cavitation.  
3. **Inspect for external leaks** – Walk around the pump, hoses, and fittings. Look for oil drips or wet spots. Tighten any loose fittings with the appropriate torque wrench.  
4. **Examine pump relief valve** – Remove the relief valve cover (de‑pressurise the system first). Ensure the valve seat is clean and the spring is not compressed. Replace the valve if damaged.  
5. **Run a pressure test** – Connect a calibrated pressure gauge to the pump outlet. Start the engine and observe the pressure reading. Compare it with the manufacturer’s nominal pressure (refer to the service catalogue).  
6. **Decision** – If pressure is within spec, the fault is cleared and the machine may be returned to service. If pressure remains low, the pump requires removal and rebuild or replacement.

---

### PROCEDURE HYD‑FILT‑03: Hydraulic Filter Clogged  
1. **Secure the machine** – Same safety steps as above.  
2. **Locate the hydraulic filter** – Usually mounted on the pump housing or in the hydraulic circuit box.  
3. **Relieve system pressure** – Open the drain valve and allow fluid to flow into a catch container.  
4. **Remove the filter element** – Use the filter wrench; note the direction of flow arrows.  
5. **Inspect the element** – If the media is dark, saturated, or the flow path is obstructed, the filter is clogged.  
6. **Replace with a new filter** – Install the new element in the same orientation, torque the housing to the specified value (see catalogue).  
7. **Bleed the system** – Close the drain valve, start the engine, and operate the controls slowly to purge air.  
8. **Decision** – After confirming normal hydraulic response, the fault is cleared. If pressure still drops, repeat the inspection or proceed to pump diagnostics.

---

### PROCEDURE HYD‑TEMP‑02: Over‑Temperature in Hydraulic System  
1. **Stop the machine** – Engage the emergency stop and allow the system to cool.  
2. **Check coolant level in the hydraulic cooler** – Top up with the specified coolant if below the “MIN” mark.  
3. **Inspect cooler fins and airflow** – Remove debris that may block ventilation. Ensure the fan is operating (listen for rotation).  
4. **Verify thermostat operation** – Locate the thermostat housing, feel for temperature change, and replace if stuck open or closed.  
5. **Measure fluid temperature** – Use a calibrated infrared thermometer on the hydraulic oil return line. Compare with the maximum allowable temperature in the catalogue.  
6. **Decision** – If temperature falls within limits after corrective actions, continue operation. Persistent overheating indicates a possible pump or cooler blockage and requires component removal.

---

### PROCEDURE COOL‑RAD‑02: Radiator Fan Failure  
1. **Safety first** – Shut down the engine, wait for the coolant to drop below the normal operating temperature, and disconnect the battery.  
2. **Inspect fan blades** – Look for cracks, bent blades, or foreign objects. Replace the fan if damaged.  
3. **Test fan motor** – Apply the appropriate test voltage to the fan motor terminals (use a test lead). The fan should spin freely at rated speed.  
4. **Check fan relay and wiring** – Measure continuity of the relay coil and the harness. Replace any faulty relay or damaged wire.  
5. **Verify coolant flow** – Ensure the water pump impeller rotates and that the radiator hoses are not collapsed.  
6. **Decision** – Once the fan operates correctly and coolant temperature stabilises, the fault is cleared. If the fan still does not engage, the electrical control module must be inspected.

---

### PROCEDURE COOL‑TEMP‑01: Engine Coolant Over‑Temperature  
1. **Stop the machine** – Engage the parking brake and allow the engine to cool for a short period.  
2. **Check coolant level** – Open the radiator cap (use a rag) and fill to the “MAX” line with the specified coolant mixture.  
3. **Inspect radiator for blockage** – Remove the radiator cap and look for debris inside the core. Flush the radiator if necessary.  
4. **Examine water pump** – Verify that the pump shaft rotates smoothly and that the impeller is not worn. Replace if abnormal wear is found.  
5. **Test thermostat** – Remove and submerge in hot water; it should open at the rated temperature. Replace if it fails to open.  
6. **Decision** – If coolant temperature returns to normal operating range, the machine may be used. Continued overheating requires a full cooling‑system diagnostic.

---

### PROCEDURE ENG‑OILP‑01: Engine Oil Pressure Low  
1. **Secure the excavator** – Same initial safety steps.  
2. **Check oil level** – Pull the dipstick, wipe clean, re‑insert, and read the level. Add oil to the “MAX” mark if low.  
3. **Inspect oil filter** – Remove the filter and examine the media. Replace if clogged.  
4. **Examine oil pump** – Listen for abnormal noises when the engine is cranked. If the pump is noisy or sluggish, it may need rebuilding.  
5. **Verify pressure sensor wiring** – Check connector pins for corrosion; clean and reseat.  
6. **Decision** – If oil pressure returns to the catalogue‑specified range, operation may continue. Persistent low pressure mandates pump replacement.

---

### PROCEDURE ENG‑AIR‑01: Air Intake Restriction  
1. **Engine off, key removed** – Open the air‑filter housing.  
2. **Inspect filter element** – Replace if the media is dirty or damaged.  
3. **Check intake ducting** – Ensure no hoses are kinked or cracked. Clear any debris from the intake path.  
4. **Verify turbocharger (if equipped)** – Spin the turbine by hand; it should rotate freely. Look for oil leakage around the housing.  
5. **Decision** – After re‑assembly, start the engine and confirm normal idle RPM and boost pressure. If performance is still poor, further turbo‑charger inspection is required.

---

### PROCEDURE ENG‑WIF‑01: Engine Water‑In‑Fuel (Water in Fuel)  
1. **Stop the engine** – Drain the fuel tank into a clean container.  
2. **Inspect fuel for water** – Look for a milky appearance or separate water layer.  
3. **Use fuel‑water separator** – Pass the fuel through the separator as per the service manual.  
4. **Replace fuel filter** – Install a new filter to capture any remaining moisture.  
5. **Refill with clean fuel** – Use only the specified fuel grade.  
6. **Decision** – After the fuel system is cleared, restart the engine and monitor for abnormal noises or mis‑fires. If symptoms persist, the fuel pump may be contaminated and should be inspected.

---

### PROCEDURE DPF‑SOOT‑01: Diesel Particulate Filter (DPF) Soot Accumulation  
1. **Engine warm‑up** – Bring the engine to normal operating temperature.  
2. **Initiate active regeneration** – Follow the catalogue procedure to command a regeneration cycle (usually via the control panel).  
3. **Monitor exhaust temperature** – Ensure it reaches the required regeneration temperature (refer to the service catalogue).  
4. **If regeneration fails** – Perform a forced regeneration using the diagnostic tool.  
5. **Inspect DPF for physical damage** – Remove the DPF and examine the ceramic walls for cracks. Replace if damaged.  
6. **Decision** – After successful regeneration, the fault clears. Re‑occurrence within a short interval may indicate a fuel‑system or injector issue.

---

### PROCEDURE ELE‑ALT‑01: Alternator Output Low  
1. **Safety** – Disconnect the battery before removing any wiring.  
2. **Measure alternator voltage** – With the engine running at idle, check voltage at the battery terminals; it should be within the catalogue‑specified range.  
3. **Inspect drive belt** – Verify proper tension and condition; replace if glazed or cracked.  
4. **Check alternator brushes** – Remove the alternator cover and examine brush wear. Replace brushes if length is below the minimum.  
5. **Examine wiring harness** – Look for corroded terminals or broken wires. Clean or replace as needed.  
6. **Decision** – If voltage returns to normal, the machine may continue operation. Persistent low output requires alternator replacement.

---

### PROCEDURE SWG‑VIB‑01: Swing Drive Vibration Excessive  
1. **Park on level ground and lock the swing** – Engage the swing‑lock lever.  
2. **Inspect swing‑drive bearings** – Remove the bearing caps and look for wear, scoring, or insufficient lubrication. Replace bearings that exceed the wear limit in the catalogue.  
3. **Check swing‑drive gear teeth** – Examine for chipped or worn teeth; replace the gear set if damage is found.  
4. **Verify hydraulic oil condition** – Replace oil if it is dark or contaminated, as poor lubrication can cause vibration.  
5. **Decision** – After re‑assembly, operate the swing at low speed and confirm smooth motion. If vibration remains, the swing‑drive motor may need rewinding.

---

### PROCEDURE UC‑TRK‑01: Undercarriage Track Tension Low  
1. **Secure the excavator** – Lower the boom to the ground and engage the parking brake.  
2. **Loosen the track tension bolts** – Use the specified torque wrench to release the tension.  
3. **Adjust track tension** – Move the idler or adjust the tensioning mechanism until the track is snug but can still be moved by hand.  
4. **Retighten bolts** – Torque to the value given in the catalogue.  
5. **Inspect track rollers and pins** – Replace any worn rollers or bent pins.  
6. **Decision** – After a short test run, verify that the track does not slip and that the tension remains stable. If tension drops again, check for worn sprockets.

---

### PROCEDURE GET‑WEAR‑01: Ground Engaging Tools (GET) Wear Exceeded  
1. **Stop the machine and lower the boom** – Ensure the bucket or attachment is on the ground.  
2. **Measure wear** – Use a calibrated gauge to check the cutting edge, teeth, or bucket lip against the wear limits listed in the catalogue.  
3. **Replace worn components** – Swap out teeth, bucket lips, or the entire bucket if wear exceeds limits.  
4. **Inspect mounting pins and bushings** – Replace any that show excessive play.  
5. **Decision** – After reinstalling the GET, perform a short digging test. If the attachment functions without excessive vibration or material loss, operation may continue.

---

### PROCEDURE BAT‑CELL‑01: Battery Cell Voltage Low  
1. **Safety** – Wear insulated gloves and eye protection.  
2. **Measure individual cell voltages** – With a digital multimeter, check each cell while the battery is at rest. Any cell below the minimum voltage specified in the catalogue must be addressed.  
3. **Equalise charge** – Connect a charger capable of equalising and run the cycle as per the battery manual.  
4. **Replace defective cells** – If a cell does not recover after equalising, replace the cell or the entire battery pack.  
5. **Decision** – After re‑testing, if all cells are within spec, the fault is cleared. Persistent low voltage indicates a charging‑system fault.

---

### PROCEDURE BAT‑ISO‑01: Battery Isolation Switch Fault  
1. **Locate the isolation switch** – Usually mounted on the operator console or near the battery compartment.  
2. **Inspect the switch contacts** – Open the switch housing and look for corrosion or burnt contacts. Clean with contact‑cleaner spray.  
3. **Test continuity** – Use a multimeter to verify that the switch opens and closes correctly.  
4. **Replace the switch** – If continuity is intermittent or absent, install a new isolation switch.  
5. **Decision** – After restoring proper operation, verify that the machine powers up normally. If the fault recurs, check the wiring harness for hidden damage.

---  

**General Notes**  

- Always refer to the excavator’s service catalogue for torque values, temperature limits, and pressure specifications.  
- Record every fault code, corrective action, and test result in the equipment logbook.  
- If a fault cannot be cleared after the prescribed steps, tag the machine **“Do Not Operate”** and schedule a detailed inspection by qualified service personnel.  

*End of Troubleshooting Section*
