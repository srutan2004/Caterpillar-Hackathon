---
machine_class: adt
section: safety
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.825850+00:00'
---

# Safety  

This section outlines the safety principles that must be observed whenever the articulated dump truck is operated, serviced, or inspected.  All personnel—operators, maintenance staff, supervisors, and visitors—are required to read, understand, and apply these guidelines before entering the work area.

---

## 1. General Hazards  

| Hazard | Typical Cause | Control Measure |
|--------|---------------|-----------------|
| **Tip‑over** | Operating on steep slopes, uneven ground, or with an overloaded payload. | Observe the **stability envelopes** (see Procedure ADT‑ST‑01). |
| **Roll‑over** | Sudden steering inputs, high‑speed travel with the body raised, or side‑slope operation beyond limits. | Keep travel speed ≤ **1.0 kph** when the body is raised (see Procedure ADT‑ST‑02). |
| **Collision** | Blind spots, inadequate visibility, or failure to respect exclusion zones. | Use mirrors, cameras, and maintain prescribed proximity distances (see Procedure ADT‑EX‑01). |
| **Mechanical failure** | Lack of preventive maintenance, damaged hydraulic lines, or worn tires. | Follow the preventive‑maintenance schedule in the Maintenance Manual. |
| **Noise & vibration** | Engine and hydraulic system operation. | Wear hearing protection and limit exposure time. |
| **Dust & airborne particles** | Loading/unloading dry material. | Use dust‑suppression methods and wear respiratory protection when needed. |

---

## 2. Exclusion Zones & Pedestrians  

> **WARNING:** Unauthorized entry into the exclusion zones is a primary cause of serious injury.  

### PROCEDURE ADT‑EX‑01: Establish and Enforce Exclusion Zones  

1. **Define zones** around the dump truck using the proximity values in the SPEC table:  

   | Zone | Distance from any part of the vehicle | Action Required |
   |------|----------------------------------------|-----------------|
   | **Warning** | ≤ **6 m** | No personnel may enter. Only trained operators may be present. |
   | **Caution** | > 6 m and ≤ **12 m** | Only essential personnel wearing high‑visibility clothing may be present; maintain visual contact with the operator. |
   | **Advisory** | > 12 m and ≤ **25 m** | Pedestrians may pass, but must remain alert and give way to the vehicle. |

2. **Mark the zones** with cones, tape, or painted lines that are clearly visible from all directions.  
3. **Post signage** at each zone boundary stating the distance and required PPE.  
4. **Assign a spotter** when the vehicle operates in the Caution or Warning zones, especially during loading/unloading or on congested sites.  
5. **Re‑evaluate** the zones whenever the vehicle’s configuration changes (e.g., body height adjustment) or the site layout is altered.  

---

## 3. Seatbelt and ROPS  

> **WARNING:** Failure to wear the seatbelt or to use a functional ROPS (Roll‑Over Protective Structure) can result in fatal injuries during a tip‑over event.  

### PROCEDURE ADT‑SE‑01: Seatbelt Use and Monitoring  

1. **Fasten the seatbelt** before any movement of the vehicle.  
2. The seatbelt system provides a **grace period of 5 seconds** after the driver initiates motion before an alarm sounds.  
3. If the belt remains unfastened **after 20 seconds**, the system escalates to a **hard‑stop** and an audible/visual alarm.  
4. **Do not** attempt to override the alarm. The operator must stop, fasten the belt, and reset the system before proceeding.  

### PROCEDURE ADT‑RO‑01: ROPS Inspection  

1. Visually inspect the ROPS frame for cracks, deformation, or missing fasteners **daily** before operation.  
2. Verify that the **anchor points** for the seatbelt are secure and free of corrosion.  
3. Perform a **functional test** of the ROPS latch mechanism weekly: engage and release the latch three times, confirming smooth operation.  
4. Record all inspections in the vehicle logbook; any defect must be **corrected before the next use**.  

---

## 4. Working Near Utilities & Overhead Lines  

> **WARNING:** Contact with live electrical conductors can cause electrocution, fire, or severe equipment damage.  

### PROCEDURE ADT‑UT‑01: Identify and Isolate Utilities  

1. **Obtain utility maps** and conduct a visual walk‑around to locate underground and overhead services.  
2. Establish a **minimum clearance** of **6 m** (Warning zone) from any overhead line. If the line voltage is unknown, treat it as high‑voltage and apply the full warning distance.  
3. Use a **non‑conductive spotter pole** to verify clearance when the line height is uncertain.  

### PROCEDURE ADT‑UT‑02: Safe Operation Near Overhead Lines  

1. **Never** raise the dump body while within the 6 m warning distance of an overhead line.  
2. If work must occur closer than 12 m (Caution zone), **de‑energize** the line or obtain written clearance from the utility provider.  
3. Deploy a **qualified electrical safety officer** to monitor the area when the vehicle operates within the Caution zone.  

---

## 5. Weather & Lightning Stop‑Work  

> **WARNING:** Operating the vehicle in severe weather (high winds, heavy rain, lightning) dramatically increases the risk of tip‑over, loss of traction, and electrical hazards.  

### PROCEDURE ADT‑WX‑01: Weather‑Related Stop‑Work  

1. **Monitor weather forecasts** and on‑site observations continuously.  
2. **Cease all operations** when any of the following conditions are present:  

   * Wind speed exceeding **16 km/h** on a slope greater than the **warning side‑slope** (16°).  
   * Heavy rain that reduces ground friction to the point where the **stability margin** falls below **1.25** (warning).  
   * Visible lightning or thunder within the surrounding area.  

3. **Park the vehicle** on level ground, lower the body, engage the parking brake, and turn off the engine.  
4. **Secure the cabin** by locking doors and activating the ROPS latch.  
5. **Resume work only after** the weather condition has cleared and a supervisor has signed off the restart.  

---

## 6. High‑Voltage Safety for Electric Variants  

> **WARNING:** Electric articulated dump trucks contain high‑voltage batteries. Direct contact can cause severe burns or death.  

### PROCEDURE ADT‑HV‑01: Pre‑Start High‑Voltage Checks  

1. Verify that the **high‑voltage interlock system** is functional (indicator lamp green).  
2. Confirm that **all personnel** within the 6 m warning zone are wearing insulated gloves and dielectric footwear.  
3. Ensure that **no conductive tools** are left on the ground or in the cab.  

### PROCEDURE ADT‑HV‑02: Emergency Shutdown  

1. In the event of a battery fault, collision, or fire, **activate the emergency stop** button located on the operator console.  
2. The system will **isolate the high‑voltage bus** within **5 seconds** and sound an audible alarm.  
3. Only **qualified electric‑service personnel** may approach the vehicle after shutdown; they must wear **voltage‑rated PPE** and use insulated tools.  

### PROCEDURE ADT‑HV‑03: Maintenance Isolation  

1. Before any battery‑related service, **disconnect the high‑voltage connector** using the lock‑out/tag‑out (LOTO) procedure.  
2. Place a **high‑voltage lock** on the isolation point and attach a **warning tag** indicating “High‑Voltage Isolated – Do Not Re‑Energize”.  
3. Verify isolation with a **voltage tester** (reading must be zero) before commencing work.  

---

## 7. Stability Envelopes – Quick Reference  

| Envelope | Advisory | Caution | Warning |
|----------|----------|---------|---------|
| **Stability Margin** (ratio) | ≥ 1.8 | ≥ 1.5 | < 1.25 |
| **Side‑Slope** (°) | — | ≤ 12° | ≤ 16° |
| **Tip‑Slope** (°) | — | ≤ 5° | ≤ 8° |
| **Payload Ratio** (payload / rated capacity) | — | ≤ 1.0 | > 1.1 |
| **Travel Speed (body raised)** (kph) | — | ≤ 1.0 | — |

Operators should **consult the stability envelope table** before each lift. If any parameter falls into the **Caution** range, reduce speed, adjust load position, or change the operating slope. If a **Warning** condition is approached, **stop the vehicle immediately** and re‑evaluate the task.

---

### Summary  

- Maintain prescribed **exclusion zones** (6 m warning, 12 m caution, 25 m advisory).  
- Always wear the **seatbelt**; the system provides a 5‑second grace period and escalates after 20 seconds.  
- Verify **ROPS integrity** daily and before each shift.  
- Keep a safe distance from **utilities**; treat any unknown line as high‑voltage.  
- Stop work during **adverse weather** and follow the lightning stop‑work protocol.  
- For electric models, respect **high‑voltage safety** procedures, including LOTO and emergency shutdown.  

Adhering to these procedures protects personnel, preserves equipment, and ensures compliance with regulatory safety standards.
