---
machine_class: excavator
section: pre_start
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.861051+00:00'
---

# Pre‑Start Walk‑Around  
*Purpose: Verify that the excavator is safe and ready for operation before engine start.*  

| Item ID | Description (label_key) | Critical? | Photo Requirement |
|---------|--------------------------|-----------|-------------------|
| tracks | walkaround.item.tracks | No | optional |
| hoses | walkaround.item.hoses | Yes | on_issue |
| leaks | walkaround.item.leaks | Yes | on_issue |
| bucket_teeth | walkaround.item.bucket_teeth | No | on_issue |
| fluid_levels | walkaround.item.fluid_levels | Yes | none |
| mirrors_cameras | walkaround.item.mirrors_cameras | Yes | none |
| lights_beacon | walkaround.item.lights_beacon | No | none |
| seatbelt | walkaround.item.seatbelt | Yes | on_issue |
| fire_extinguisher | walkaround.item.fire_extinguisher | Yes | none |
| steps_handrails | walkaround.item.steps_handrails | No | none |
| battery_connector* | walkaround.item.battery_connector | Yes | on_issue |
| coolant_battery* | walkaround.item.coolant_battery | Yes | none |

\* Items marked with an asterisk appear only on the electric‑drive version of the machine.

The walk‑around must be completed within **60 seconds** (time_budget_s) for each machine type.

---

## PROCEDURE walkaround_excavator: Diesel‑Powered Excavator Walk‑Around  

1. **Allocate Time** – Set a stopwatch or timer for **60 seconds**.  
2. **Inspect Tracks** – Walk around the under‑carriage and visually check track tension, wear, and missing links.  
   - *Photo*: optional – take a picture only if a defect is observed.  
3. **Check Hoses** – Examine all hydraulic and fuel hoses for cracks, abrasions, or loose fittings.  
   - *Critical*: Yes – any damaged hose **blocks start**.  
   - *Photo*: on_issue – photograph any hose that appears compromised.  
4. **Search for Leaks** – Look for fluid drips on the ground and on components (hydraulic, fuel, coolant).  
   - *Critical*: Yes – leaks **block start**.  
   - *Photo*: on_issue – capture the leak location.  
5. **Bucket Teeth** – Verify that bucket teeth are securely attached and not excessively worn.  
   - *Photo*: on_issue – document missing or broken teeth.  
6. **Fluid Levels** – Open each reservoir (engine oil, hydraulic oil, coolant) and confirm level is within the marked “full” range.  
   - *Critical*: Yes – low or missing fluid **blocks start**.  
   - No photo required.  
7. **Mirrors & Cameras** – Ensure all mirrors are correctly positioned and cameras (if equipped) are clean and functional.  
   - *Critical*: Yes – impaired visibility **blocks start**.  
   - No photo required.  
8. **Lights & Beacon** – Verify that work‑area lights, headlamp, and beacon are intact and not cracked.  
   - *Critical*: No – a non‑functioning light does **not** prevent start, but must be reported.  
9. **Seatbelt** – Pull the seatbelt to confirm it locks and releases smoothly.  
   - *Critical*: Yes – a defective seatbelt **blocks start**.  
   - *Photo*: on_issue – photograph any damage or lock failure.  
10. **Fire Extinguisher** – Check pressure gauge, pin, and accessibility.  
    - *Critical*: Yes – missing or expired extinguisher **blocks start**.  
    - No photo required.  
11. **Steps & Handrails** – Walk the access steps and handrails; ensure they are secure and free of debris.  
    - *Critical*: No – report any loose hardware.  

> **WARNING:** If any **critical** item (hoses, leaks, fluid levels, mirrors/cameras, seatbelt, fire extinguisher) is found defective, **do not start the machine**. Immediately tag the equipment “Do Not Operate” and proceed to the reporting step.

### Reporting Defects  

| Defect Category | Reporting Method | Documentation Required |
|-----------------|------------------|------------------------|
| Critical (blocks start) | Stop work, inform supervisor, complete “Equipment Defect Report” form | Photo (if required), description, location, time |
| Non‑critical | Log in daily walk‑around checklist, attach photo if applicable | Checklist entry, optional photo |

1. Fill out the **Pre‑Start Walk‑Around Checklist** on the machine’s logbook or electronic tablet.  
2. Attach any required photos to the checklist entry.  
3. Submit the completed checklist to the maintenance supervisor within **30 minutes** of the walk‑around.  
4. For critical defects, the supervisor will issue a **Work‑Stop Order** and arrange corrective action before another walk‑around is performed.

---

## PROCEDURE walkaround_excavator_electric: Electric‑Drive Excavator Walk‑Around  

The electric version follows the same sequence as the diesel version, with two additional critical items.

1. **Allocate Time** – Set a timer for **60 seconds**.  
2. **Tracks** – Same as diesel procedure (optional photo).  
3. **Hoses** – Same as diesel procedure (critical, photo on_issue).  
4. **Leaks** – Same as diesel procedure (critical, photo on_issue).  
5. **Bucket Teeth** – Same as diesel procedure (photo on_issue).  
6. **Battery Connector** – Inspect the high‑voltage battery connector for secure locking, corrosion, or damaged pins.  
   - *Critical*: Yes – a loose or damaged connector **blocks start**.  
   - *Photo*: on_issue – capture connector condition.  
7. **Coolant / Battery** – Verify coolant level in the battery thermal‑management system and that the battery temperature indicator is within normal range.  
   - *Critical*: Yes – abnormal temperature or low coolant **blocks start**.  
   - No photo required.  
8. **Mirrors & Cameras** – Same as diesel (critical).  
9. **Lights & Beacon** – Same as diesel (non‑critical).  
10. **Seatbelt** – Same as diesel (critical, photo on_issue).  
11. **Fire Extinguisher** – Same as diesel (critical).  

> **WARNING:** For the electric model, a **faulty battery connector or abnormal battery coolant/temperature** is as serious as a hydraulic leak. Do not attempt to start the machine until these issues are resolved.

### Reporting Defects (Electric Model)

Use the same table and steps as the diesel model, adding the battery‑related items to the defect description.  

1. Record the condition of the **battery connector** and **coolant/battery** fields in the checklist.  
2. Attach any required photos (connector, coolant level gauge, temperature read‑out).  
3. Submit the checklist to the maintenance supervisor; a critical battery issue will trigger a **High‑Voltage Safety Review** before power can be applied.

---

## QUICK REFERENCE CHECKLIST (Print‑out)

```
[ ] Tracks – OK / Issue (photo)  
[ ] Hoses – OK / Issue (photo)   *Critical*  
[ ] Leaks – OK / Issue (photo)   *Critical*  
[ ] Bucket Teeth – OK / Issue (photo)  
[ ] Fluid Levels – OK / Issue     *Critical*  
[ ] Mirrors/Cameras – OK / Issue *Critical*  
[ ] Lights & Beacon – OK / Issue  
[ ] Seatbelt – OK / Issue (photo) *Critical*  
[ ] Fire Extinguisher – OK / Issue  
[ ] Steps/Handrails – OK / Issue  
[ ] Battery Connector – OK / Issue (photo) *Critical* (electric only)  
[ ] Coolant/Battery – OK / Issue *Critical* (electric only)  
```

- **Mark “OK”** if the item passes inspection.  
- **Mark “Issue”** and attach a photo when a problem is found.  
- **If any *Critical* item is marked “Issue,”** the machine **must not be started** until the defect is corrected and the checklist re‑signed.

---

### Summary  

- Complete the walk‑around in **60 seconds**.  
- Focus on **critical** items; any failure blocks start.  
- Photograph only the items specified (optional, on_issue, or none).  
- Record findings on the official checklist and forward to maintenance within **30 minutes**.  
- Follow the reporting flow for both critical and non‑critical defects to ensure safe, reliable operation of the excavator.
