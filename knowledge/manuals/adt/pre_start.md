---
machine_class: adt
section: pre_start
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.824844+00:00'
---

## Pre‑Start Walkaround  
*Reference: `adt_30t.walkaround`*  

The pre‑start walkaround is the first line of defence against equipment damage, operator injury, and site‑related downtime.  The operator must complete the walkaround **within the allotted time budget of 60 seconds** and verify every item listed below before attempting to start the articulated dump truck.  Any **critical** item that fails must be reported and corrected before the machine may be started.

---  

### PROCEDURE walkaround_adt: Perform Pre‑Start Walkaround  

| Step | Action | Item ID | Label (system key) | Critical? | Photo Required? |
|------|--------|---------|--------------------|-----------|-----------------|
| 1 | Approach the vehicle from the driver’s side and visually inspect the **tyres** for damage, inflation, and tread wear. | tyres | `walkaround.item.tyres` | **Yes** | Capture a photo **only if a defect is found**. |
| 2 | Scan the chassis, hydraulic lines, and under‑body for **leaks** (oil, hydraulic fluid, coolant, fuel). | leaks | `walkaround.item.leaks` | **Yes** | Capture a photo **only if a leak is observed**. |
| 3 | Examine the **dump body** for cracks, dents, loose pins, and proper latch operation. | dump_body | `walkaround.item.dump_body` | **Yes** | Capture a photo **only if damage is present**. |
| 4 | Verify that the **articulation lock** is fully engaged and the lock indicator is green. | articulation_lock | `walkaround.item.articulation_lock` | **Yes** | No photo required. |
| 5 | Check all **fluid levels** (engine oil, hydraulic oil, coolant, fuel). Ensure each sight‑glass is within the “full” band and that caps are secure. | fluid_levels | `walkaround.item.fluid_levels` | **Yes** | No photo required. |
| 6 | Perform a quick **brake test**: press the foot pedal and confirm firm pressure and audible brake‑release. | brakes_test | `walkaround.item.brakes_test` | **Yes** | No photo required. |
| 7 | Inspect **mirrors and cameras** for cleanliness, proper alignment, and functional display. | mirrors_cameras | `walkaround.item.mirrors_cameras` | **Yes** | No photo required. |
| 8 | Verify that **lights and beacon** operate (head‑lamps, work lights, warning beacon). | lights_beacon | `walkaround.item.lights_beacon` | No | No photo required. |
| 9 | Confirm the **seatbelt** is intact, free of cuts, and can be fastened securely. | seatbelt | `walkaround.item.seatbelt` | **Yes** | Capture a photo **only if the belt is damaged or does not latch**. |
|10| Locate the **fire extinguisher**, check pressure gauge, and ensure the pin is intact. | fire_extinguisher | `walkaround.item.fire_extinguisher` | **Yes** | No photo required. |
|11| **Record** the completion time. The total walkaround must not exceed **60 seconds**. | – | – | – | – |

> **WARNING:**  
> If any **critical** item (marked “Yes” in the *Critical?* column) is found to be out of service, the vehicle **must not be started**. The defect must be reported immediately to the maintenance supervisor and corrected before any further operation.

#### Detailed Execution Guidance  

1. **Tyres** – Run your hand lightly over the sidewall to feel for cuts or bulges. Use a tyre pressure gauge if the vehicle is equipped with a portable gauge; otherwise, rely on visual cues (e.g., under‑inflation sag).  
2. **Leaks** – Look for fresh fluid stains on the ground and on metal surfaces. Pay special attention to the hydraulic hose bundles near the articulation joint.  
3. **Dump Body** – Open the body fully, then close it slowly while listening for abnormal noises that could indicate loose hinges.  
4. **Articulation Lock** – The lock lever should be in the “locked” position and the indicator lamp should be green. If the lock does not engage, do not proceed.  
5. **Fluid Levels** – Remove each dip‑stick, wipe clean, re‑insert, and read the level. Top‑off only with the correct fluid type as specified in the operator’s handbook.  
6. **Brakes Test** – With the vehicle in neutral, press the brake pedal fully. The pedal should feel solid and not sink to the floor. Release and listen for a distinct release click.  
7. **Mirrors / Cameras** – Wipe any dirt or condensation. Verify that camera feeds display on the cab monitor without distortion.  
8. **Lights / Beacon** – Activate the work lights and beacon using the control switch; observe illumination from a safe distance.  
9. **Seatbelt** – Pull the belt fully out, fasten it, and pull it to ensure it locks. Check the webbing for fraying.  
10. **Fire Extinguisher** – The pressure gauge needle must be in the green zone. The safety pin should be intact; do not tamper with the extinguisher unless a fire is present.  

#### Reporting Defects  

| Defect Category | Reporting Method | Information to Include |
|-----------------|------------------|------------------------|
| Critical (tyres, leaks, dump body, articulation lock, fluid levels, brakes, mirrors/cameras, seatbelt, fire extinguisher) | Immediate verbal report to the on‑site supervisor **and** entry into the electronic walkaround log. | Item ID, description of defect, location (e.g., left front tyre), photo (if required), time of discovery. |
| Non‑critical (lights/beacon) | Log in the walkaround sheet; notify maintenance at the next scheduled stop. | Item ID, description, any observed abnormal behavior. |

> **WARNING:**  
> Starting the vehicle with an unresolved critical defect can result in loss of control, hydraulic failure, or fire. Always err on the side of safety.

#### Time Management Tips  

- **Practice** the sequence repeatedly; muscle memory reduces the time spent on each step.  
- Keep a **handheld checklist** (paper or tablet) that mirrors the table above; tick each item as you complete it.  
- Use the **60‑second timer** on the cab display (if equipped) to stay within the budget.  

---  

### QUICK REFERENCE CHECKLIST (Print‑out Friendly)

```
[ ] Tyres – damage / inflation? (photo if defect)
[ ] Leaks – oil / hydraulic / coolant? (photo if defect)
[ ] Dump body – cracks / latch? (photo if defect)
[ ] Articulation lock – engaged, green indicator
[ ] Fluid levels – oil, hydraulic, coolant, fuel – full
[ ] Brakes – pedal firm, release click
[ ] Mirrors / cameras – clean, aligned, display OK
[ ] Lights & beacon – all functional
[ ] Seatbelt – intact, latches, no cuts (photo if defect)
[ ] Fire extinguisher – pressure OK, pin intact
Time elapsed: ____ seconds (must ≤ 60)
```

Keep this sheet in the cab for rapid reference.  

---  

#### Summary  

- Complete the **walkaround** in **≤ 60 seconds**.  
- All items marked **critical** must be **clear** before engine start.  
- Document any defect, attach required photos, and **report** immediately.  
- Only after a **clear** walkaround may the operator proceed to the **Start‑Engine** procedure.  

Following this disciplined walkaround routine protects the machine, the operator, and the work site, and ensures compliance with the manufacturer’s safety standards.
