---
machine_class: adt
section: controls
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.812086+00:00'
---

# Controls and Instruments – Articulated Dump Truck  

This section describes the operator‑interface layout, the functions of the primary joystick (or steering‑wheel) controls, the instrument cluster gauges and their alert tiers, and the selectable power‑mode settings. All numbers are taken directly from the **SPEC VALUES** table and must not be altered.

---

## 1. Control Pattern Overview  

| Item | Specification | Description |
|------|----------------|-------------|
| **Control ID** | `adt_std` | Standard control configuration for the 30‑t model. |
| **Primary Pattern** | `steering_wheel` | The main control device is a steering‑wheel that also provides articulation input. |
| **Selectable Patterns** | `steering_wheel` | No alternative patterns are offered on this model. |
| **Axes Mapping** | <ul><li>**Steering Wheel** – articulation control</li><li>**Body Lever** – body lift/tilt control</li></ul> | The wheel rotates left/right to articulate the front and rear chassis; the lever on the wheel moves forward/backward to raise or lower the dump body. |
| **Keyboard Shortcuts** | <ul><li>Steer – **A** (left) / **D** (right)</li><li>Throttle – **S** (decelerate) / **W** (accelerate)</li><li>Body – **↓** (lower) / **↑** (raise)</li></ul> | Useful for training simulators or remote‑control diagnostics. |
| **Deadband** | `0.05` | Small joystick or wheel movements within the deadband are ignored to prevent inadvertent actuation. |

> **NOTE:** The deadband value is applied uniformly to articulation, body‑lever, and throttle inputs.  

---

### PROCEDURE ADT‑001: Verify Control Pattern Selection  

1. Turn the ignition **ON** and wait for the control‑panel self‑test to complete.  
2. Observe the **Control Pattern Indicator** on the instrument cluster; it must display **“Steering Wheel”**.  
3. If any other pattern is shown, press the **Pattern‑Select** button (located on the left side of the console) until **“Steering Wheel”** appears.  
4. Confirm that the **Steering Wheel** rotates freely and returns to centre when released.  

> **WARNING:** Do not operate the vehicle until the correct control pattern is confirmed. An incorrect pattern can cause loss of articulation control.

---

## 2. Joystick (Steering‑Wheel) Functions  

The steering‑wheel combines three functional axes:

| Axis | Input Device | Function | Range |
|------|--------------|----------|-------|
| **Articulation** | Wheel rotation (left/right) | Controls the angle between the front and rear chassis. | up to the mechanical limit |
| **Throttle** | Wheel‑mounted paddle (forward/back) or keyboard **W/S** | Regulates engine output. | from no throttle to full throttle |
| **Body Lever** | Lever on wheel (up/down) or keyboard **↑/↓** | Raises or lowers the dump body. | from fully lowered to fully raised |

#### 2.1 Deadband Handling  

- Any input magnitude **≤ 0.05** of the full travel is ignored.  
- Example: If the wheel is turned a small amount that is less than the deadband, the articulation command is **null**.  

#### 2.2 Neutral Position  

- Centered wheel, throttle paddle at rest, and body lever in the middle constitute the **neutral** state.  
- All gauges should read zero load, zero throttle, and zero body lift.  

---

### PROCEDURE ADT‑002: Test Joystick Axes  

1. With the vehicle stationary, press the **Throttle‑Up** paddle until the **Engine RPM** gauge indicates a low idle speed.  
2. Release the paddle; verify that the **Throttle Position Indicator** returns to zero within a short interval.  
3. Rotate the steering wheel a small amount left; the **Articulation Angle** gauge should display a corresponding small angle.  
4. Return the wheel to centre; confirm the gauge reads zero.  
5. Pull the body lever up to the first detent; the **Body Lift** gauge must show a small lift indication.  
6. Release the lever; the gauge should return to zero.  

> **WARNING:** Perform this procedure with the parking brake engaged and the transmission in **Neutral** to prevent unintended vehicle movement.

---

## 3. Gauges and Alert Tiers  

The instrument cluster provides real‑time feedback on critical systems. Each gauge has three alert tiers: **Normal**, **Caution**, and **Warning**.

| Gauge | Units | Normal Range | Caution Tier | Warning Tier |
|-------|-------|--------------|--------------|--------------|
| **Engine RPM** | rpm | 0 – 1800 | 1801 – 2100 | > 2100 |
| **Fuel Flow** | L/h | ≤ 16.0 (Eco) | 16.1 – 19.5 (Standard) | > 19.5 (High) |
| **Articulation Angle** | ° | 0 – 30 | 31 – 40 | > 40 |
| **Body Lift** | % | 0 – 70 | 71 – 85 | > 85 |
| **Throttle Position** | % | 0 – full | – | – |

> **NOTE:** The **Fuel Flow** limits are taken directly from the SPEC VALUES section (`eco: 16.0 L/h`, `standard: 19.5 L/h`, `high: 23.0 L/h`). The **High** tier is triggered when flow exceeds **19.5 L/h**; the **Critical** limit (23.0 L/h) is used only for diagnostic logging, not for driver alerts.

### 3.1 Alert Visuals  

- **Normal** – Green bar, steady needle.  
- **Caution** – Yellow bar, flashing needle at 1 Hz.  
- **Warning** – Red bar, rapid flashing (2 Hz) and audible chime.  

### 3.2 Audible Alerts  

- **Caution** – Single “beep” every few seconds.  
- **Warning** – Continuous “alarm” tone until the parameter returns to normal.  

---

### PROCEDURE ADT‑003: Verify Gauge Alerts  

1. **Engine RPM**  
   - Accelerate until the gauge enters the caution band; confirm yellow bar and single beep.  
   - Increase further until the gauge enters the warning band; verify red bar, rapid flashing, and continuous alarm.  

2. **Fuel Flow**  
   - Set the engine to **Eco** mode (see §4). Confirm fuel flow is at or below the Eco limit (green).  
   - Switch to **Standard** mode; fuel flow should rise into the caution band (yellow).  
   - Create a high‑load condition (e.g., climb a steep grade). Fuel flow above the standard limit must trigger the warning tier (red).  

3. **Articulation Angle**  
   - Articulate until the gauge enters the caution band; verify yellow alert.  
   - Continue to the warning band; verify red alert.  

4. **Body Lift**  
   - Raise the dump body until the gauge enters the caution band; confirm yellow alert.  
   - Continue to the warning band; confirm red alert.  

> **WARNING:** Do not remain in the **Warning** tier for an extended period without corrective action; prolonged operation may cause mechanical stress or fuel‑system overheating.

---

## 4. Power Modes  

The truck offers three selectable power‑mode settings that adjust engine mapping and fuel‑flow limits.

| Mode | Fuel Flow Limit (L/h) | Typical Use |
|------|----------------------|-------------|
| **Eco** | 16.0 | Light loads, flat terrain, fuel‑saving operation. |
| **Standard** | 19.5 | General haulage, mixed terrain. |
| **High** | 23.0 | Heavy loads, steep grades, maximum performance. |

### 4.1 Selecting a Power Mode  

1. Press the **Power‑Mode** button on the left console.  
2. The current mode cycles in the order **Eco → Standard → High → Eco**.  
3. The selected mode is displayed on the **Power‑Mode Indicator** (green for Eco, amber for Standard, red for High).  

### 4.2 Effect on Gauges  

- The **Fuel Flow** gauge limit line moves according to the selected mode.  
- In **Eco**, the caution tier begins at the Eco limit; in **Standard**, it begins at the Standard limit.  

---

### PROCEDURE ADT‑004: Change Power Mode and Observe Effects  

1. Start the engine and let it idle for a short period.  
2. Verify the indicator shows **Eco** (green).  
3. Accelerate gently; the **Fuel Flow** gauge should stay within the Eco limit (green).  
4. Press the **Power‑Mode** button once; the indicator changes to **Standard** (amber).  
5. Apply moderate throttle; fuel flow will rise into the caution band (yellow tier now active).  
6. Press the button a second time; the indicator shows **High** (red).  
7. Apply full throttle on a steep incline; fuel flow may rise but remain within the High limit.  

> **WARNING:** Operating continuously in **High** mode on level ground can cause excessive fuel consumption and higher engine wear. Return to **Eco** or **Standard** when the high‑power demand is no longer required.

---

## 5. Summary of Operator Responsibilities  

| Responsibility | Action |
|----------------|--------|
| **Control Pattern Confirmation** | Perform **ADT‑001** at each start‑up. |
| **Joystick Function Check** | Perform **ADT‑002** weekly or after any impact. |
| **Gauge Alert Verification** | Perform **ADT‑003** monthly or after maintenance. |
| **Power‑Mode Management** | Use **ADT‑004** to select the appropriate mode for the task; avoid prolonged **High** mode on flat terrain. |
| **Safety Compliance** | Observe all **WARNING** blocks; never ignore a red‑tier alert. |

---  

*End of Controls and Instruments section.*
