---
machine_class: adt
section: operating
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.822629+00:00'
---

## Operating Techniques – Articulated Dump Truck  

*This section describes best‑practice operating methods that maximise cycle efficiency, protect the hydraulic system, maintain stability on slopes, and minimise fuel consumption. All numeric limits are taken directly from the SPEC VALUES table.*

---  

### PROCEDURE OP001: Optimising the Load‑Dump‑Return Cycle  

1. **Approach the load site at a travel speed that keeps the body **raised** no faster than the **caution** envelope of **1.0 kph**.**  
   - This prevents excessive hydraulic demand and reduces the risk of cavitation in the pump.  

2. **Position the truck so the load is centred within the body envelope** (rear body width **2.95 m**, track width **2.6 m**).  
   - A centred load keeps the **payload_ratio** ≤ **1.0** (caution) and avoids the **warning** limit of **1.1**.  

3. **Lower the body only after the bucket is fully under the load** and the hydraulic pressure has stabilised.  
   - Use the **high_rpm_threshold** of **1400 rpm** as a guide; if the engine speed spikes above this while lowering, pause and allow pressure to settle.  

4. **Lift the load at a controlled rate**:  
   - Do not exceed the **travel_speed_body_raised_kph** caution value of **1.0 kph** while the body is raised.  
   - This limits hydraulic flow to a level that prevents cavitation and protects the pump.  

5. **Travel to the dump site with the body raised** at the **loaded speed factor** of **0.78** of the **max_travel_speed_kph** (**55 kph**).  
   - This provides the recommended loaded travel speed.  

6. **Dump the load** by fully lowering the body, then **wait for the hydraulic pressure to stabilise** before re‑raising.  

7. **Return to the loading point with the body raised** at the same loaded speed.  

> **WARNING:** Operating the body‑raised travel speed above **1.0 kph** can cause pump cavitation, leading to premature wear and possible hydraulic failure.  

---  

### PROCEDURE OP002: Avoiding Cavitation and Relief‑Stall Conditions  

| Condition | Symptom | Action |
|-----------|---------|--------|
| **Pump cavitation** | Rapid engine RPM rise, audible “gurgling”, loss of lift speed | Reduce body‑raised travel speed to ≤ 1.0 kph; allow hydraulic pressure to build before continuing. |
| **Relief‑stall** (hydraulic relief valve opens) | Engine RPM drops, sudden loss of lift force | Stop lifting, wait for pressure to settle, then resume at a slower rate. |

1. **Monitor engine RPM** continuously. If it approaches the **high_rpm_threshold** of **1400 rpm** while the body is moving, **immediately reduce hydraulic flow** by slowing the body‑raised travel speed.  

2. **Do not operate the pump at full flow for more than 30 seconds** without a pause. A short pause (≈ 5 s) allows the pump’s inlet pressure to recover, eliminating cavitation.  

3. **Use the “eco” work fuel mode** (fuel consumption **16.0 l/h**) when performing light lifts or when the load is within the **payload_ratio** caution limit. Lower pump demand reduces the likelihood of cavitation.  

> **WARNING:** Repeated relief‑stall events can damage the hydraulic relief valve and reduce system life.  

---  

### PROCEDURE OP003: Working on Slopes – Stability Management  

1. **Determine the slope angle** before entering the work area. Use on‑board inclinometer or visual reference.  

2. **Observe the side‑slope envelope**:  
   - **Caution** limit = **12 °**  
   - **Warning** limit = **16 °**  

   - **If the slope ≤ 12 °**, operate with normal payload (up to rated **28 t**) but keep the **payload_ratio** ≤ **1.0** (caution).  
   - **If the slope is between 12 ° and 16 °**, reduce payload to maintain a **payload_ratio** ≤ **1.0** and increase the **stability_margin** to at least **1.8** (advisory).  

3. **Maintain the stability margin**:  
   - **Advisory** = **1.8** (preferred)  
   - **Caution** = **1.5**  
   - **Warning** = **1.25**  

   - Use the vehicle’s load‑monitoring system (if equipped) to verify the margin stays above **1.5** on slopes.  

4. **Avoid side‑loading** the body while on a slope. Load and dump only in the direction of the slope’s downhill side to keep the centre of gravity within the lateral tipping lines (derived from the tipping_lines data).  

5. **When approaching a tip‑slope** (front‑to‑rear):  
   - **Caution** limit = **5 °**  
   - **Warning** limit = **8 °**  

   - Do not travel with the body raised on slopes steeper than **5 °**. If a tip‑slope greater than **5 °** must be crossed, lower the body and travel at the **caution** speed of **1.0 kph** (body‑raised speed).  

> **WARNING:** Exceeding the **warning** side‑slope of **16 °** or tip‑slope of **8 °** can cause lateral or longitudinal overturn, even with the payload within limits.  

---  

### PROCEDURE OP004: Idling Management and Fuel Economy  

| Parameter | Value (from SPEC VALUES) |
|-----------|--------------------------|
| Minimum idle episode | **180 s** |
| Excessive idle episode | **600 s** |
| Maximum idle ratio (idle / total cycle time) | **0.30** |
| Idle fuel consumption | **3.0 l/h** |

1. **Limit each idle period** to **no less than 180 seconds** (to allow engine warm‑up) and **no more than 600 seconds**.  

2. **Track the idle ratio** for the current shift:  
   - **Idle Ratio** = (Total idle time) / (Total operating time).  
   - Keep this ratio **≤ 0.30**.  

3. **Select the appropriate work‑fuel mode** based on job demand:  

| Mode | Fuel Consumption (l/h) | Recommended Use |
|------|------------------------|-----------------|
| Eco | **16.0** | Light loads, flat terrain, frequent stops |
| Standard | **19.5** | Typical operations, mixed terrain |
| High | **23.0** | Heavy loads, steep grades, high‑speed travel |

4. **When idling for more than 5 minutes**, shut down the engine if the vehicle will be stationary for longer than **10 minutes**. Restart using the **pre‑heat** function to avoid excessive wear.  

5. **Use cruise control** on long, straight runs to maintain a constant speed and avoid unnecessary acceleration, which raises fuel use.  

> **WARNING:** Prolonged idling beyond **600 s** not only wastes fuel (3 l/h) but also raises engine temperature, increasing the risk of oil degradation and component wear.  

---  

### PROCEDURE OP005: General Tips for Efficient Cycle Execution  

| Tip | Description |
|-----|-------------|
| **Plan the route** | Minimise travel distance between load and dump points; use the **rear_swing_radius** of **5.743 m** to select the tightest feasible turning radius without exceeding the **stability_margin**. |
| **Pre‑position the truck** | Arrive with the body already raised to the **caution** travel speed (≤ 1.0 kph) so the lift can commence immediately. |
| **Batch loads when possible** | If the site permits, load multiple piles before dumping to reduce the number of cycles. Keep the **payload_ratio** ≤ **1.0** to stay within the caution envelope. |
| **Monitor hydraulic temperature** | High temperature can indicate excessive flow; reduce body‑raised speed or switch to **eco** mode. |
| **Regularly inspect the under‑carriage** | Check for debris that could affect the **rear_overhang** (2.9 m) and wheel‑track clearance, especially on uneven ground. |

---  

### QUICK REFERENCE TABLE  

| Parameter | Value | Application |
|-----------|-------|-------------|
| **Operating mass** | **23 500 kg** | Overall vehicle weight for stability calculations |
| **Rated payload** | **28 t** | Maximum permissible load |
| **Body capacity** | **17.5 m³** | Volume of material per load |
| **Max travel speed (empty)** | **55 kph** | Upper limit for unloaded travel |
| **Loaded travel speed** | **0.78 × 55 kph** | Recommended speed when body is raised |
| **Side‑slope caution** | **12 °** | Maximum safe side slope for normal operation |
| **Side‑slope warning** | **16 °** | Upper limit; avoid crossing |
| **Tip‑slope caution** | **5 °** | Maximum safe front‑to‑rear slope with body raised |
| **Tip‑slope warning** | **8 °** | Upper limit; avoid crossing |
| **Stability margin advisory** | **1.8** | Desired minimum for safe operation |
| **Stability margin caution** | **1.5** | Minimum acceptable |
| **Stability margin warning** | **1.25** | Below this, stop operation |
| **Idle fuel** | **3.0 l/h** | Fuel use while idling |
| **Work fuel – eco** | **16.0 l/h** | Best fuel economy mode |
| **Work fuel – standard** | **19.5 l/h** | Typical operation |
| **Work fuel – high** | **23.0 l/h** | Heavy‑load, high‑speed mode |

---  

**End of Operating Techniques section**. Follow these procedures to achieve safe, efficient, and economical operation of the articulated dump truck.
