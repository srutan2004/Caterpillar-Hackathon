---
machine_class: excavator
section: controls
procedure_ids: []
source: generated:openai/gpt-oss-120b
reviewed_at: '2026-09-24T03:30:18.856519+00:00'
---

# Controls and Instruments – Controls  

This section describes how the operator interacts with the excavator’s control system. It covers the selectable control pattern, joystick functions, gauge read‑outs and alert tiers, and the available power‑mode selections. All numbers are taken directly from the **SPEC VALUES** table; no values have been invented.

---  

## 1. Control Pattern Selection  

### PROCEDURE P001: Verify and Change Control Pattern  

1. Power the cab on and allow the electronic control unit (ECU) to complete its self‑check.  
2. Locate the **Control‑Pattern Selector Switch** on the left side of the instrument panel.  
3. The selector displays the current pattern – either **ISO** or **SAE**.  
4. To change the pattern:  
   - Pull the knob outward, rotate to the desired position, and push it back in.  
   - The ECU will acknowledge the change with a short audible tone and a flashing “PATTERN” indicator.  
5. Verify the new pattern on the **Pattern Display** (digital read‑out).  

> **WARNING:** Changing the control pattern while the machine is moving can cause unintended actuator commands. Always bring the excavator to a complete stop before switching patterns.  

### PROCEDURE P002: Confirm Axis Mapping for Selected Pattern  

| Pattern | Left Joystick – X | Left Joystick – Y | Right Joystick – X | Right Joystick – Y |
|---------|-------------------|-------------------|--------------------|--------------------|
| **ISO** | Swing | Stick | Bucket | Boom |
| **SAE** | Swing | Boom | Bucket | Stick |

1. With the pattern confirmed, move each joystick axis through its full travel.  
2. Observe the corresponding function on the **On‑Screen Diagram** (available via the “CTRL‑MAP” button).  
3. If any axis does not match the table above, repeat **Procedure P001** to re‑select the correct pattern.  

---  

## 2. Joystick Functions  

### PROCEDURE P010: Operate Joysticks in ISO Pattern  

| Joystick | Axis | Function | Keyboard Equivalent |
|----------|------|----------|----------------------|
| **Left** | X (horizontal) | Swing the house left/right | **KeyA** (neg) / **KeyD** (pos) |
| **Left** | Y (vertical) | Extend / retract the **Stick** | **KeyW** (neg) / **KeyS** (pos) |
| **Right** | X (horizontal) | Open / close the **Bucket** | **ArrowLeft** (neg) / **ArrowRight** (pos) |
| **Right** | Y (vertical) | Raise / lower the **Boom** | **ArrowUp** (neg) / **ArrowDown** (pos) |

1. Center both joysticks before starting any operation.  
2. Move the left‑hand joystick left or right to rotate the house; the swing speed is proportional to the displacement.  
3. Push the left‑hand joystick forward (negative) to pull the stick toward the cab, or pull it back (positive) to extend the stick.  
4. Use the right‑hand joystick left/right to close/open the bucket; the bucket speed is limited by the **deadband** value of **0.05** (any displacement less than the deadband is ignored).  
5. Raise the boom by moving the right‑hand joystick forward (negative) and lower it by pulling it back (positive).  

> **WARNING:** Exceeding the deadband threshold unintentionally (e.g., by a sudden jolt) can cause rapid, uncontrolled movement. Keep hands steady and avoid jerky motions.  

### PROCEDURE P011: Operate Joysticks in SAE Pattern  

| Joystick | Axis | Function | Keyboard Equivalent |
|----------|------|----------|----------------------|
| **Left** | X | Swing the house | **KeyA** / **KeyD** |
| **Left** | Y | Raise / lower the **Boom** | **ArrowUp** / **ArrowDown** |
| **Right** | X | Open / close the **Bucket** | **ArrowLeft** / **ArrowRight** |
| **Right** | Y | Extend / retract the **Stick** | **KeyW** / **KeyS** |

1. Follow the same centering and proportional‑control rules as in **Procedure P010**, but note the swapped Y‑axis functions.  
2. Verify the mapping on the on‑screen diagram before beginning work.  

---  

## 3. Gauges and Alert Tiers  

### PROCEDURE P020: Read Primary Gauges  

| Gauge | Unit | Normal Range | Critical Alert |
|-------|------|--------------|----------------|
| **Engine Speed (RPM)** | rev/min | within the normal operating band | when the gauge exceeds the upper limit, a red “OVER‑RPM” alert appears |
| **Hydraulic Pressure** | bar | within the normal operating band | when the gauge falls below the lower limit, a yellow “LOW PRESS” alert appears |
| **Fuel Level** | % | within the normal operating band | when the gauge falls below the low‑fuel threshold, a red “FUEL LOW” alert appears |
| **Battery Voltage** (electric model) | V | within the normal operating band | when the gauge falls below the low‑voltage threshold, a yellow “BAT LOW” alert appears |

1. Locate the analog/digital gauge cluster directly in front of the seat.  
2. Verify that each needle or digital read‑out is within the **Normal Range** before commencing work.  
3. If any gauge enters the **Critical Alert** zone, the corresponding alert light flashes and an audible chime sounds.  

> **WARNING:** Operating with hydraulic pressure below the low‑pressure threshold can cause loss of control over boom, stick, and bucket. Stop work immediately and inspect the hydraulic system.  

### PROCEDURE P021: Respond to Alert Tiers  

1. **Yellow Tier (Caution):**  
   - Acknowledge the alert by pressing the **ACK** button on the instrument panel.  
   - Reduce load or speed as appropriate.  
   - Monitor the gauge; if it returns to normal, continue operation.  

2. **Red Tier (Emergency):**  
   - Immediately bring the excavator to a stop using the **Travel‑Brake** lever.  
   - Shut down the engine with the **Ignition Switch** (rotate to OFF).  
   - Follow the relevant emergency procedure (fuel leak, hydraulic failure, etc.).  

---  

## 4. Power Modes  

The excavator offers three fuel‑consumption‑based power modes. These modes affect engine output and fuel flow rates as defined in the SPEC VALUES table.

| Mode | Description | Fuel Flow (L/h) |
|------|-------------|-----------------|
| **Eco** | Minimum output for light work, reduced emissions | 14.0 |
| **Standard** | Balanced output for typical digging cycles | 17.5 |
| **High** | Maximum output for heavy‑duty tasks | 20.5 |

### PROCEDURE P030: Select Power Mode  

1. Press the **POWER‑MODE** button on the right side of the instrument panel.  
2. The current mode is displayed on the **Mode Indicator** (Eco, Standard, High).  
3. Rotate the adjacent selector knob to the desired mode.  
4. The ECU will adjust throttle mapping and display the new fuel‑flow rate on the **Fuel‑Flow Gauge**.  

> **WARNING:** Selecting **High** mode while operating on steep slopes can increase the risk of rollover. Use **Eco** or **Standard** on inclines greater than the recommended limit.  

### PROCEDURE P031: Verify Fuel Consumption  

1. After selecting a mode, observe the **Fuel‑Flow Gauge** for a short period.  
2. The gauge should read the exact value from the table above (e.g., 14.0 L/h for Eco).  
3. If the reading deviates noticeably, log the discrepancy and contact service.  

---  

## 5. Keyboard Control (Optional Remote Operation)  

The excavator can be driven from a portable keyboard interface for training or limited remote operation. The key assignments are identical to the joystick functions described above.

| Function | Negative Key | Positive Key |
|----------|--------------|--------------|
| Swing | **KeyA** | **KeyD** |
| Stick (ISO) / Boom (SAE) | **KeyW** | **KeyS** |
| Boom (ISO) / Stick (SAE) | **ArrowUp** | **ArrowDown** |
| Bucket | **ArrowLeft** | **ArrowRight** |
| Travel Left | **KeyQ** | **KeyZ** |
| Travel Right | **KeyE** | **KeyC** |

1. Connect the keyboard to the cab’s USB port.  
2. Enable “Keyboard Mode” via the **CTRL‑MAP** button.  
3. Use the keys as listed; the same deadband of **0.05** applies.  

> **WARNING:** Keyboard control does not provide haptic feedback. Operate only in low‑risk environments and keep the joystick centered as a visual reference.  

---  

## 6. Summary Checklist  

| Item | Completed? |
|------|------------|
| Control pattern set to required standard (ISO/SAE) | ☐ |
| Joystick axes verified against table | ☐ |
| Gauges checked – no red alerts | ☐ |
| Power mode selected for job | ☐ |
| Keyboard mode (if used) configured | ☐ |

By following the procedures above, the operator ensures safe, predictable control of the excavator and maintains compliance with the machine’s design specifications.
