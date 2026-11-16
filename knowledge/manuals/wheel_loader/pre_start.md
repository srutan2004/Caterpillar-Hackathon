---
machine_class: wheel_loader
section: pre_start
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.874565+00:00'
---

## Pre‑Start Walk‑around  
*Purpose: Verify that the wheel loader is safe and ready for operation before starting the engine.*  

| Item ID | Description (label key) | Critical? | Photo Required on Issue |
|---------|--------------------------|-----------|--------------------------|
| tyres | `walkaround.item.tyres` | **Yes** | on_issue |
| hoses | `walkaround.item.hoses` | **Yes** | on_issue |
| leaks | `walkaround.item.leaks` | **Yes** | on_issue |
| bucket_teeth | `walkaround.item.bucket_teeth` | No | on_issue |
| articulation_lock | `walkaround.item.articulation_lock` | **Yes** | none |
| fluid_levels | `walkaround.item.fluid_levels` | **Yes** | none |
| brakes_test | `walkaround.item.brakes_test` | **Yes** | none |
| mirrors_cameras | `walkaround.item.mirrors_cameras` | **Yes** | none |
| lights_beacon | `walkaround.item.lights_beacon` | No | none |
| seatbelt | `walkaround.item.seatbelt` | **Yes** | on_issue |

> **NOTE:** The entire walk‑around must be completed within **60 seconds** as defined in the specification.  

---

### PROCEDURE walkaround_wheel_loader: Pre‑start Walk‑around  

1. **Approach the machine safely**  
   - Walk on the designated walk‑around path, keeping clear of moving parts and pinch points.  
   - Ensure the loader is in neutral, the parking brake is applied, and the engine is off.  

2. **Inspect tyres** (`tyres`) – *critical*  
   - Visually check for cuts, bulges, low pressure, or missing tread.  
   - **If any defect is found,** take a photo and **do not start** the machine. Report to the supervisor and arrange tyre repair/replacement.  

> **WARNING:** Operating with damaged or under‑inflated tyres can cause loss of control, excessive wear, and catastrophic failure of the suspension.

3. **Examine hydraulic and fuel hoses** (`hoses`) – *critical*  
   - Look for cracks, abrasions, loose fittings, or fluid seepage.  
   - If a hose is compromised, photograph the issue, stop the start‑up, and tag the loader as “Do Not Operate” until the hose is repaired or replaced.  

> **WARNING:** A ruptured hose can lead to sudden loss of hydraulic pressure, fire, or environmental contamination.

4. **Check for fluid leaks** (`leaks`) – *critical*  
   - Scan the under‑carriage, engine compartment, and hydraulic reservoirs for oil, coolant, or fuel drips.  
   - Any visible leak requires a photo, immediate reporting, and corrective action before engine start.  

5. **Review bucket teeth condition** (`bucket_teeth`) – *non‑critical*  
   - Ensure teeth are not excessively worn or missing.  
   - If wear is severe, note it in the maintenance log; the loader may still be started, but schedule a bucket service at the next maintenance window.  

6. **Verify articulation lock is engaged** (`articulation_lock`) – *critical*  
   - Confirm the lock lever is fully seated and the indicator shows “LOCKED.”  
   - If the lock does not engage, do not start the machine. Report the fault and arrange mechanical inspection.  

7. **Confirm fluid levels** (`fluid_levels`) – *critical*  
   - Check engine oil, coolant, hydraulic oil, and fuel levels against the sight‑glass or dip‑stick markings.  
   - Low or contaminated fluid must be topped up or replaced before start‑up. Record the action in the logbook.  

8. **Perform a brakes test** (`brakes_test`) – *critical*  
   - With the loader still stationary, release the parking brake and gently apply the service brake.  
   - The machine should come to a smooth stop within a short distance.  
   - If braking is spongy, uneven, or fails, **do not start** and tag the loader for brake service.  

> **WARNING:** Faulty brakes present a severe safety hazard and may cause uncontrolled movement.

9. **Inspect mirrors and cameras** (`mirrors_cameras`) – *critical*  
   - Adjust side mirrors for a clear view of the rear and sides.  
   - Verify that any camera displays are functional and free of obstruction.  
   - Defective optics must be reported; the loader may not be started until visibility is restored.  

10. **Check lights and beacon** (`lights_beacon`) – *non‑critical*  
    - Turn the illumination switch on; confirm that work lights, headlamps, and the warning beacon illuminate.  
    - Record any non‑functioning lamp in the defect log; the loader can be started, but the issue must be corrected before returning to site.  

11. **Secure seatbelt** (`seatbelt`) – *critical*  
    - Pull the seatbelt fully and ensure the latch clicks.  
    - If the belt does not lock, photograph the defect and **do not start** the machine. Arrange seatbelt repair or replacement.  

12. **Document the walk‑around**  
    - Use the checklist form (or electronic tablet) to mark each item as **OK** or **Defect**.  
    - Attach any required photos (items marked “on_issue”).  
    - Sign and date the checklist.  

13. **Report defects**  
    - Submit the completed checklist to the shift supervisor or maintenance control center.  
    - For critical defects, the loader must be tagged **“Do Not Operate”** and moved to a safe location away from traffic.  
    - Non‑critical defects are logged for scheduled maintenance but do not prevent immediate operation.  

14. **Proceed to engine start** (only if **all critical items are marked OK**)  
    - Follow the standard **Engine Start** procedure in the operator manual.  

---

### QUICK REFERENCE TABLE

| Critical Item | Must be **OK** before start? | Action if NOT OK |
|---------------|------------------------------|------------------|
| Tyres | Yes | Photo → Report → Repair |
| Hoses | Yes | Photo → Tag → Repair |
| Leaks | Yes | Photo → Report → Fix |
| Articulation lock | Yes | Report → Inspect |
| Fluid levels | Yes | Top‑up/Replace → Log |
| Brakes test | Yes | Tag → Service |
| Mirrors / cameras | Yes | Report → Repair |
| Seatbelt | Yes | Photo → Report → Replace |
| Bucket teeth | No | Log for later service |
| Lights & beacon | No | Log for later service |

---

### TROUBLESHOOTING QUICK TIPS  

| Symptom | Likely Cause (from walk‑around) | Immediate Check |
|---------|--------------------------------|-----------------|
| Engine cranks but stalls | Low fuel or hydraulic oil | Verify `fluid_levels` |
| Loader lurches forward on idle | Parking brake not fully applied | Re‑check `brakes_test` |
| Unusual vibration | Damaged tyre or loose hose | Re‑inspect `tyres` and `hoses` |
| No rear‑view camera image | Camera power loss | Confirm `mirrors_cameras` status |

---

### RECORD‑KEEPING REQUIREMENTS  

- **Checklist retention:** Minimum 30 days on‑site, then archive per company policy.  
- **Photo archive:** Store images in the equipment’s digital file (file name: *loaderID_walkaround_YYYYMMDD_XX.jpg*).  
- **Defect tags:** Use a bright red “Do Not Operate” tag with the date, time, and initials of the inspector.  

---

By following this **60‑second** pre‑start walk‑around, operators ensure that all safety‑critical systems are verified, hazards are identified before they become incidents, and maintenance personnel receive timely, documented information for corrective action.
