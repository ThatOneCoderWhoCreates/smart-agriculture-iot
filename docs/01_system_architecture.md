# 01 · System Architecture

## 1. Layer model

| Layer | Responsibility | Implementation | Latency budget |
|---|---|---|---|
| **Perception** | Convert physical quantities to voltages/pulses | DHT11, capacitive soil probe, LDR divider, HC-SR04 | — |
| **Edge** | Acquire, filter, decide, actuate, aggregate | ESP32 / Arduino Uno firmware | 2 s sample, decision within one sample |
| **Actuation** | Switch mains-class load safely | opto-isolated relay → DC pump | < 1 s |
| **Network** | Deliver telemetry | WiFi 802.11 → HTTPS | 20 s publish |
| **Cloud** | Store, plot, expose | ThingSpeak channel, 6 fields | 15 s minimum write interval |
| **Analytics** | Clean, engineer, model | Python: pandas / NumPy / scikit-learn | batch |
| **Decision** | Fuse rule + three models | dashboard + `infer()` | < 50 ms per reading |

The important architectural property is that **the control loop does not depend on the
cloud**. If WiFi drops, the node keeps irrigating correctly and buffers telemetry. Cloud
and ML are advisory layers on top of a self-sufficient controller. A design where the pump
waits for an HTTP response is a design that floods or kills the crop when the link fails.

---

## 2. Data flow

```
sensors ──► analogRead / pulseIn
              │
              ├─ median-of-5 filter          reject single-sample EMI spikes
              ├─ calibration map             ADC counts → engineering units
              │
              ├─► hysteresis controller ──► relay ──► pump          [2 s loop]
              │        │
              │        └─► alert state machine ──► LEDs, buzzer, LCD
              │
              └─► accumulator (10 samples) ──► 20 s mean ──► ThingSpeak
                                                                  │
                                                    feeds.csv ◄───┘
                                                        │
   ┌────────────────────────────────────────────────────┘
   ▼
 02 preprocessing
   ├─ validity gate      (range check, −999 sentinel → NaN)         Layer-1 detector
   ├─ gap-aware imputation (time-interp ≤ 15 min, else ffill+flag)
   ├─ feature store      (lags, rates, rolling stats, physics)
   ▼
 03 modelling
   ├─ M1 RF classifier   → irrigation demand (YES/NO) + probability
   ├─ M2 RF regressor    → soil moisture at t+30 min
   └─ M3 Isolation Forest→ anomaly flag + score                     Layer-2 detector
   ▼
 dashboard: live values · history · predictions · anomalies · metrics
```

---

## 3. The data contract

Everything downstream depends on this frame. Define it once, in the report, and never
deviate.

```
millis, temp_c, hum_pct, soil_pct, light_pct, water_pct, pump, alert
```

| Field | Type | Unit | Range | Sentinel |
|---|---|---|---|---|
| `temp_c` | float | °C | −5 … 60 | −999 |
| `hum_pct` | float | % RH | 0 … 100 | −999 |
| `soil_pct` | float | % VWC-equivalent | 0 … 100 | −999 |
| `light_pct` | float | % full scale | 0 … 100 | −999 |
| `water_pct` | float | % of tank height | 0 … 100 | −1 (no echo) |
| `pump` | int | — | 0 / 1 | — |
| `alert` | int | code | 0–4 | — |

Alert codes: `0` normal · `1` low water · `2` high temperature · `3` both · `4` sensor fault.

---

## 4. Control law

```
lowWater = (tank ≤ 20 %) or (tank < 0)          # <0 means no ultrasonic echo
dwellOk  = (now − lastTransition) ≥ 10 s

if lowWater:                       pump ← OFF          # hard interlock
elif not pump and soil < 35 % and dwellOk:   pump ← ON
elif     pump and soil > 60 % and dwellOk:   pump ← OFF
else:                              pump ← unchanged    # dead band
```

Three design decisions worth defending:

1. **Hysteresis, not a single set-point.** With one threshold at 35 %, sensor noise of
   ±0.5 pp around the boundary toggles the relay every sample. Measured in the simulation:
   the 35/60 dead band produces **18 irrigation events in 21 days**; a single threshold
   would produce thousands of relay operations, well past the ~100 k mechanical life of a
   typical SRD-05VDC relay.
2. **The low-water check is evaluated first and overrides everything.** Running a
   centrifugal pump dry destroys the seal in minutes. Interlocks belong above the control
   logic, not inside it.
3. **Minimum dwell time.** Protects against the case where soil moisture sits exactly on a
   set-point and the median filter output oscillates by one ADC count.

---

## 5. Failure handling

| Failure | Detection | Response |
|---|---|---|
| DHT read returns NaN | `isnan()` in firmware | hold last valid value, continue |
| No ultrasonic echo (30 ms timeout) | `pulseIn() == 0` | return −1 → treated as low water → pump inhibited (fail-safe) |
| Out-of-range reading | validity gate in `02_preprocess` | → NaN, flagged, imputed if gap ≤ 15 min |
| WiFi down | `WiFi.status()` | control continues; publish retried next cycle |
| ThingSpeak HTTP 0 | return code check | rate limit hit — publish interval is 20 s ≥ 15 s so this should not occur |
| Sensor stuck / drifting | Isolation Forest (Layer 2) | flag on dashboard, operator verifies before acting |

Note the fail-safe direction: an unreadable tank sensor inhibits the pump rather than
enabling it. Failing closed is correct here because a missed irrigation cycle costs a day
of growth, whereas a dry-run pump costs the pump.

---

## 6. Why three models and not one

They answer three different questions and fail in different ways:

- **M1 (classification)** is the *decision* layer — it converts micro-climate into a binary
  action recommendation with a calibrated probability, so a marginal call can be escalated
  to a human instead of silently actuated.
- **M2 (regression)** is the *planning* layer — a number, not a verdict. It supports
  scheduling ("the field will be at 37 % at 16:00, batch it with the neighbouring plot")
  and gives the magnitude that a classifier discards.
- **M3 (unsupervised)** is the *trust* layer. M1 and M2 both assume their inputs are real.
  M3 is the only component that questions the inputs, and it must be unsupervised because
  you cannot label field faults you have not seen yet.

The dashboard fuses them: an M1 recommendation carrying an M3 flag is presented as
"verify the probe before acting", not as an actuation command.
