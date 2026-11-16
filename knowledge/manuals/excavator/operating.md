---
machine_class: excavator
section: operating
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.859036+00:00'
---

# Operating Techniques – Excavator (Generic 20 t Model)

This section describes the most efficient ways to run the machine while protecting the equipment, the operator, and the surrounding site. Follow the numbered procedures in the order presented for each task. All numeric limits are taken directly from the **SPEC VALUES** table; do not exceed them.

---

## Table of Key Values  

| Parameter | Value | Units |
|-----------|-------|-------|
| **Stability margin – advisory** | 1.8 | – |
| **Stability margin – caution** | 1.5 | – |
| **Stability margin – warning** | 1.25 | – |
| **Side‑slope limit – caution** | 10 | ° |
| **Side‑slope limit – warning** | 15 | ° |
| **Travel speed (boom raised)** | 2.0 | km h⁻¹ |
| **Swing rate near personnel** | 20 | ° s⁻¹ |
| **Relief pressure** | 350 | bar |
| **Idle‑fuel consumption** | 3.2 | L h⁻¹ |
| **Work‑fuel consumption – Eco** | 14.0 | L h⁻¹ |
| **Work‑fuel consumption – Standard** | 17.5 | L h⁻¹ |
| **Work‑fuel consumption – High** | 20.5 | L h⁻¹ |
| **Maximum dig depth** | 6.7 | m |
| **Maximum reach** | 10.2 | m |
| **Tail‑swing radius** | 2.9 | m |
| **Idle episode minimum** | 180 | s |
| **Idle episode excessive** | 600 | s |
| **Maximum idle‑time ratio** | 0.25 | – |
| **High‑RPM idle threshold** | 1 400 | rpm |

---

## PROCEDURE 01: Establish an Efficient Work Cycle  

1. **Position the machine** on firm, level ground. Verify that the **stability margin** is at least the advisory value **1.8** before beginning any cycle.  
2. **Select the appropriate fuel‑consumption mode** on the control panel:  
   - **Eco** for light‑to‑moderate loads.  
   - **Standard** for typical rated payload (**2.2 t**).  
   - **High** only when maximum power is required (e.g., hard‑rock digging).  
3. **Set boom‑raised travel speed** ≤ **2.0 km h⁻¹**. Faster travel raises the centre of gravity and can breach the caution stability margin.  
4. **Begin the cycle**:  
   a. **Swing** the house to the next dig point at ≤ **20 ° s⁻¹** when personnel are within the swing arc.  
   b. **Lower the boom** using a smooth, constant‑rate motion; avoid abrupt stops that cause hydraulic pressure spikes.  
   c. **Extend the stick** to the required reach, staying inside the **reach envelope** (max 10.2 m).  
   d. **Load the bucket** to no more than the rated capacity **1.2 m³** (≈ 2.2 t).  
   e. **Lift** the load using a steady pressure increase; do not exceed the **relief pressure** of **350 bar**.  
   f. **Swing** to the dump point, again respecting the **20 ° s⁻¹** limit.  
   g. **Release** the material with a controlled bucket opening; avoid “ball‑throwing” which creates cavitation in the hydraulic lines.  
5. **Return** to the original dig position and repeat.  

> **WARNING:** Exceeding the **relief pressure** of **350 bar** can damage hydraulic seals and cause uncontrolled flow, leading to cavitation and component failure.

**Tip:** Keep the cycle time as short as practical while maintaining the above limits. Shorter cycles reduce idle periods and improve overall fuel economy.

---

## PROCEDURE 02: Avoid Cavitation and Relief‑Stall Conditions  

1. **Maintain hydraulic flow** above the cavitation threshold by never allowing the pump to operate at a pressure lower than the system’s minimum working pressure (generally 30 % of relief pressure).  
2. **Do not operate the bucket at full speed** when the hydraulic pressure is near the **relief pressure** of **350 bar**. Reduce the flow rate by easing the joystick.  
3. **Monitor the pressure gauge** continuously during lift and swing. If the needle approaches the relief setting, pause the motion and allow pressure to settle before continuing.  
4. **Use the “Eco” fuel mode** for light loads; lower engine RPM reduces pump output and the likelihood of pressure spikes.  
5. **Check for air entrainment** in the hydraulic lines after long idle periods (see Procedure 05). Bleed the system if bubbles are visible.  

> **WARNING:** Operating with cavitation can erode pump components, cause relief‑valve chatter, and lead to sudden loss of power.

---

## PROCEDURE 03: Working on Sloped Ground  

1. **Determine the slope angle** with a site‑survey tool.  
2. **Compare** the measured angle to the envelope limits:  
   - **Caution** at **10 °** – operate only with reduced swing speed and travel speed.  
   - **Warning** at **15 °** – cease operation; reposition to a flatter area.  
3. **Align the machine** so that the **track gauge** (2.39 m) is as perpendicular as possible to the slope direction.  
4. **Reduce travel speed** to well below the **2.0 km h⁻¹** limit; a typical safe value is well below that limit on a 10 ° slope.  
5. **Limit boom extension** to keep the centre of gravity within the **stability margin** of **1.5** (caution) or **1.25** (warning). Use the reach envelope chart to verify that the boom‑stick‑bucket combination does not exceed the lateral envelope at the given slope.  
6. **Avoid side‑swing** (swinging the house left/right) on slopes steeper than the caution limit; if swing is required, keep the rate ≤ **20 ° s⁻¹** and monitor the stability margin continuously.  

> **WARNING:** Exceeding the **side‑slope warning** of **15 °** can cause lateral tip‑over even if the stability margin appears adequate.

---

## PROCEDURE 04: Optimising Idling and Fuel Economy  

1. **When the machine is stopped** but the engine must remain on (e.g., waiting for a crew signal), keep the idle period **≥ 180 s** and **≤ 600 s**.  
2. **Track idle‑time ratio** (idle time ÷ total cycle time). It must never exceed **0.25**. If the ratio approaches this limit, either:  
   - Increase productive work time, or  
   - Shut down the engine and restart when work resumes.  
3. **Observe engine RPM**; if it rises above **1 400 rpm** while idling, the high‑RPM threshold has been breached—reduce idle load by turning off non‑essential auxiliaries (lights, heater).  
4. **Select the appropriate fuel‑consumption mode** before each shift:  
   - **Eco** (14 L h⁻¹) for light work, low‑load travel, and standby.  
   - **Standard** (17.5 L h⁻¹) for normal digging.  
   - **High** (20.5 L h⁻¹) only when maximum hydraulic power is required.  
5. **Use the “travel‑with‑boom‑raised” speed limit** of **2.0 km h⁻¹**; higher speeds increase fuel burn and reduce stability.  

> **WARNING:** Prolonged idling beyond **600 s** raises engine temperature, accelerates wear, and can trigger the **excessive idle** alarm, leading to automatic shutdown.

---

## PROCEDURE 05: Monitoring and Adjusting for Real‑Time Conditions  

| Parameter | Monitoring Method | Action if Limit Exceeded |
|-----------|-------------------|--------------------------|
| **Stability margin** | On‑board stability indicator | Reduce boom extension, move to flatter ground |
| **Side‑slope angle** | Inclinometer or site survey | Stop work, reposition |
| **Travel speed (boom raised)** | Speedometer | Reduce throttle to ≤ 2.0 km h⁻¹ |
| **Swing rate near personnel** | Visual observation + swing‑rate display | Slow swing to ≤ 20 ° s⁻¹ |
| **Hydraulic pressure** | Pressure gauge | Ease joystick, allow pressure to fall below relief |
| **Idle‑time ratio** | Cycle‑log software | Increase productive time or shut down engine |
| **Engine RPM (idle)** | Tachometer | Reduce auxiliary loads, return to idle RPM < 1 400 |

1. **Log all readings** at the start of each shift and after any major change in terrain or load.  
2. **Adjust operating mode** (Eco/Standard/High) based on the logged fuel consumption versus the target values (14 L h⁻¹, 17.5 L h⁻¹, 20.5 L h⁻¹).  
3. **Perform a brief inspection** after any episode of relief‑pressure activation to verify that no hydraulic fluid has leaked and that the relief valve is functioning correctly.  

---

## PROCEDURE 06: Safe Shutdown and Restart  

1. **Park** the machine on level ground, lower the boom and stick fully, and place the bucket on the ground.  
2. **Engage the travel lock** and set the swing lock.  
3. **Turn off the engine** after a minimum idle period of **180 s** to allow oil pressure to stabilize.  
4. **Wait at least 30 s** before restarting to let the hydraulic system settle.  
5. **Perform a pre‑start check**: verify oil level, coolant temperature, and that no warning lights are illuminated.  

> **WARNING:** Restarting the engine while the hydraulic pressure is still high can cause a surge that damages the pump and relief valve.

---

### Summary of Best Practices  

- Keep **stability margin** ≥ **1.8** (advisory) and never let it drop below **1.25** (warning).  
- Operate on slopes ≤ **10 °** (caution) and stop at **15 °** (warning).  
- Limit **boom‑raised travel** to **2.0 km h⁻¹** and **swing rate** near people to **20 ° s⁻¹**.  
- Observe **relief pressure** of **350 bar**; never exceed it.  
- Maintain **idle episodes** between **180 s** and **600 s**, with an overall **idle‑time ratio** ≤ **0.25**.  
- Choose the correct **fuel‑consumption mode** to match the job’s demand and achieve the target fuel rates (Eco 14 L h⁻¹, Standard 17.5 L h⁻¹, High 20.5 L h⁻¹).  

By adhering to these procedures, operators will achieve high productivity, extend component life, and minimise fuel consumption while maintaining a safe working environment.
