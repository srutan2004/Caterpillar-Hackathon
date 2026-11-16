---
machine_class: excavator
section: safety
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.863055+00:00'
---

# Safety  

The safety section of the operator & maintenance manual provides the essential information needed to protect personnel, equipment, and the work site. All procedures are written for a **generic 20‑t excavator** (hydraulic or electric) and reference the exact values listed in the specification table.  

---  

## 1. General Hazards  

| Hazard | Typical Cause | Mitigation |
|--------|---------------|------------|
| **Tip‑over** | Working on unstable ground, excessive side‑slope, or exceeding stability envelope | Observe the **Stability Margin** envelope (see Procedure 001) and never operate on slopes steeper than the **caution** limit of **10 °** (warning at **15 °**). |
| **Pinch points** | Swinging boom, bucket, or under‑carriage components | Keep hands, clothing, and tools clear of moving parts. Use the **Swing‑Rate Near‑Person** limit of **20 °/s** (caution). |
| **Hydraulic failure** | Over‑pressurised system, damaged hoses | Do not exceed the **Relief Pressure** of **350 bar**. Follow lock‑out/tag‑out (LOTO) procedures before servicing. |
| **Noise & vibration** | Engine, hydraulic pump, boom movement | Wear hearing protection and limit exposure time according to site policy. |
| **Dust & fumes** | Excavation in dry soil, diesel exhaust (hydraulic model) | Use water misting, dust extraction, and respiratory protection when required. |

> **WARNING:** Failure to respect any of the limits in the tables below can result in equipment damage, personal injury, or fatality.  

---  

## 2. Exclusion Zones & Pedestrians  

### PROCEDURE 001: Establishing Exclusion Zones  

1. **Identify the work area** and mark three concentric zones around the excavator using high‑visibility tape or cones.  
2. **Advisory Zone – 15 m** – Personnel may enter but must remain alert and maintain communication with the operator.  
3. **Caution Zone – 8 m** – Only essential personnel may enter, and they must receive direct supervision from the operator.  
4. **Warning Zone – 4 m** – No personnel are permitted; this is the “keep‑out” area while the machine is operating.  

> **WARNING:** If a pedestrian breaches the **Warning Zone (4 m)**, the operator must immediately stop all motion, sound the alarm, and verify the person’s safety before resuming work.  

### PROCEDURE 002: Controlling Pedestrian Access  

1. Post **“No Entry – Excavator Operating”** signs at all entry points to the exclusion zones.  
2. Assign a **spotter** when work is performed near public walkways or where visibility is limited.  
3. Use a **two‑way radio** or hand signals to maintain continuous contact with the spotter.  

---  

## 3. Seat‑belt & ROPS (Rollover Protective Structure)  

### PROCEDURE 003: Seat‑belt Use  

| Parameter | Value |
|-----------|-------|
| **Grace period before escalation** | **5 s** |
| **Escalation after non‑use** | **20 s** |

1. Instruct the operator to **fasten the seat‑belt** before any movement of the machine.  
2. The machine’s seat‑belt reminder will sound for **5 s** after the ignition is turned on. If the belt remains unfastened, a second reminder will sound after **20 s** and the machine will **enter a safe‑stop mode** (engine idle, boom lowered).  
3. Verify that the **ROPS** is intact, free of cracks, and that the seat‑belt latch is not obstructed before each shift.  

> **WARNING:** Operating the excavator without a fastened seat‑belt or with a compromised ROPS voids the safety envelope and may cause severe injury in a tip‑over event.  

---  

## 4. Working Near Utilities & Overhead Lines  

### PROCEDURE 004: Utility Clearance  

| Clearance | Minimum Distance |
|-----------|------------------|
| **Underground utilities (cables, pipes)** | visual confirmation required |
| **Overhead power lines** | 4 m (warning zone) |
| **Live high‑voltage lines (> 11 kV)** | 10 m (additional safety buffer) |

1. Obtain **utility maps** and conduct a **walk‑around survey** before starting work.  
2. Use a **non‑contact voltage detector** to verify the presence of live overhead lines.  
3. If any line is within the **Warning Zone (4 m)**, **stop work** and contact the utility owner for clearance or line de‑energisation.  

> **WARNING:** Contact with an energized line can cause electrocution, fire, or catastrophic equipment damage.  

### PROCEDURE 005: Overhead Line Swing‑Rate Control  

1. When the boom or swing is operating within the **caution zone (8 m)** of an overhead line, limit the **swing rate** to **20 °/s** (caution).  
2. If the operator must exceed this rate for a brief maneuver, obtain written permission from the site safety officer and ensure a **spotter** is positioned in the **Advisory Zone (15 m)**.  

---  

## 5. Weather & Lightning – Stop‑Work Criteria  

### PROCEDURE 006: Weather Monitoring  

1. Check the **local weather forecast** at the start of each shift and regularly thereafter.  
2. **Heavy rain, strong winds, or reduced visibility** trigger a **stop‑work**.  

### PROCEDURE 007: Lightning Protection  

1. When **thunder is audible** or **lightning is observed nearby**, cease all operations immediately.  
2. Lower the boom, stop the swing, and park the excavator on level ground with the **engine off**.  
3. Remain sheltered until a safe period has passed after the last observed lightning strike.  

> **WARNING:** Operating the excavator during a lightning storm can cause electrical arcing through the hydraulic system, leading to loss of control or fire.  

---  

## 6. High‑Voltage Safety for Electric Variant  

The **excavator_20t_electric** shares the same proximity and envelope values as the hydraulic model, but additional precautions are required for the high‑voltage battery system.  

### PROCEDURE 008: Battery High‑Voltage Precautions  

| Parameter | Value |
|-----------|-------|
| **Relief pressure (hydraulic)** | **350 bar** (applies to hydraulic circuit; electric model uses the same pressure for auxiliary hydraulics) |
| **Maximum safe approach to live parts** | visual inspection only |

1. **Lock‑out/Tag‑out** the high‑voltage battery before any maintenance. Use the designated high‑voltage lock‑out device and verify isolation with a **voltage tester**.  
2. Do **not** attempt to service the battery pack in wet conditions or when the machine is on a **slope greater than 10 °** (caution).  
3. In the event of a **battery fire**, use a **Class D dry‑powder extinguisher** and evacuate the area. Do not attempt to extinguish with water.  

> **WARNING:** Contact with the high‑voltage system can cause severe electric shock or arc flash. Only qualified personnel may work on the battery.  

---  

## 7. Summary of Key Safety Limits  

| Envelope | Advisory | Caution | Warning |
|----------|----------|---------|---------|
| **Proximity Zones (m)** | 15 | 8 | 4 |
| **Stability Margin (× weight)** | 1.8 | 1.5 | 1.25 |
| **Side‑Slope (°)** | – | 10 | 15 |
| **Travel Speed – Boom Raised (kph)** | – | 2.0 | – |
| **Swing Rate Near Person (°/s)** | – | 20 | – |
| **Seat‑belt Grace (s)** | 5 | – | – |
| **Seat‑belt Escalation (s)** | – | 20 | – |
| **Relief Pressure (bar)** | – | – | 350 |

---  

### Final Note  

All operators must be trained on these procedures and must sign a **Safety Acknowledgement Form** before being authorized to operate the excavator. Regular refresher training (minimum annually) is required to keep safety knowledge current. Non‑compliance with any of the limits or steps described in this section will be recorded as a safety incident and may result in disciplinary action.  

---  

*End of Safety Section* (≈ 900 words).
