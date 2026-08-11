# 05 · Test Cases and Expected Results

Two independent test suites. Do not mix them — they prove different things.

- **Suite A — firmware / hardware**, run in Tinkercad. Proves the control law and alerts.
- **Suite B — end-to-end ML**, run in the dashboard. Proves the models on held-out data.

Every value in Suite B was produced by running the trained models; the cursor positions are
the ones the dashboard's scenario selector jumps to.

---

## Suite A — Firmware tests (Tinkercad)

Set-points: soil start 35 %, soil stop 60 %, tank minimum 20 %, temperature alert 35 °C,
minimum dwell 10 s.

### A1 · Normal conditions

| | |
|---|---|
| **Setup** | soil pot ≈ 50 %, distance slider 12 cm (≈ 80 % tank), TMP36 ≈ 25 °C |
| **Expected** | pump OFF, green LED ON, yellow OFF, red OFF, buzzer silent |
| **LCD page 1** | `T:25.0°C H:xx%` / `Soil:50% PUMP:OF` |
| **LCD page 2** | `Light:xx% Tank:80` / `Status: NORMAL ` |
| **Serial** | `...,25.00,xx,50.00,xx,80.00,0,0` — trailing `0,0` = pump off, alert none |
| **Pass** | alert code 0 for 60 s continuously |

### A2 · Dry soil → irrigation activated

| | |
|---|---|
| **Setup** | from A1, turn the soil pot down through 35 % |
| **Expected** | at the first sample below 35 %: relay clicks, motor spins, yellow LED ON |
| **Serial** | pump field flips `0 → 1` within one 2 s sample |
| **Pass** | transition occurs below 35 %, not at 34 % or 36 % |
| **Trap** | if the relay chatters, the dwell timer is not working — check `MIN_PUMP_MS` |

### A3 · Soil recovers → irrigation stopped

| | |
|---|---|
| **Setup** | from A2, turn the soil pot **up** slowly |
| **Expected** | pump stays ON through 40 %, 50 %, 55 % — **this is the point of the test** — and stops only above 60 % |
| **Serial** | pump `1 → 0` at the first sample above 60 % |
| **Pass** | no state change anywhere in the 35–60 % dead band |
| **Why it matters** | it demonstrates hysteresis rather than a single threshold. If the pump stops at 35 % you have implemented a plain comparator |

### A4 · Low tank → pump disabled + alert

| | |
|---|---|
| **Setup** | soil pot below 35 % (so the pump *wants* to run), drag the ultrasonic slider past 36 cm |
| **Expected** | pump forced OFF **despite dry soil**, red LED ON, buzzer 900 Hz, alert code `1` |
| **LCD page 2** | `! LOW WATER LVL` |
| **Recovery** | bring the slider back under 36 cm → pump resumes automatically |
| **Pass** | the interlock overrides the irrigation demand, not the other way round |

### A5 · High temperature warning

| | |
|---|---|
| **Setup** | raise the TMP36 slider past 35 °C, tank healthy |
| **Expected** | red LED ON, buzzer 1500 Hz short chirp, alert code `2` |
| **Critical** | the pump's behaviour is **unchanged** — heat is a warning, not an interlock |
| **Combined** | set low tank *and* high temperature → alert code `3`, 2000 Hz, `! LOW H2O+HEAT` |

### A6 · Sensor fault

| | |
|---|---|
| **Setup** | disconnect the HC-SR04 ECHO wire mid-simulation |
| **Expected** | `pulseIn` times out → returns −1 → treated as low water → **pump inhibited**, alert code `4`, 400 Hz |
| **Pass** | the system fails **closed** (pump off), not open |
| **Say this** | a missed irrigation cycle costs a day of growth; a dry-run pump costs the pump |

---

## Suite B — End-to-end ML scenarios (dashboard)

Run `streamlit run dashboard/app.py`, pick the scenario from the sidebar. The cursor value
is shown so you can return to the exact reading.

| ID | Scenario | Cursor | Timestamp | Matches in test set |
|---|---|---|---|---|
| S1 | Normal conditions | 6211 | 2026-03-20 07:31 | 615 |
| S2 | Dry soil → irrigation activated | 5234 | 2026-03-19 15:14 | 30 |
| S3 | Soil sufficient → irrigation stopped | 5555 | 2026-03-19 20:35 | 16 |
| S4 | Low water tank → pump disabled | 152 | 2026-03-16 02:32 | 305 |
| S5 | High temperature warning | 2435 | 2026-03-17 16:35 | 433 |
| S6 | Abnormal readings → anomaly detected | 1446 | 2026-03-17 00:06 | 64 |

### S1 · Normal environmental conditions

| Channel | Value |
|---|---|
| Temperature | 19 °C |
| Humidity | 68 % |
| Soil moisture | 56.3 % |
| Light | 22 % |
| Tank | 78.5 % |
| Pump | OFF |

| Model | Output | Ground truth |
|---|---|---|
| M1 demand probability | **0.003 → NO** | 0 ✓ |
| M2 soil at *t*+30 | **56.3 %** | 56.7 % (error 0.4 pp) ✓ |
| M3 score | **−0.0344** (flags above 0) → NORMAL | not a fault ✓ |

All banners green. This is the reference state; show it first so the examiner has a baseline
for the alarm states.

### S2 · Dry soil → irrigation activated

| Channel | Value |
|---|---|
| Temperature | 35 °C |
| Humidity | 34 % |
| Soil moisture | **35.0 %** — exactly at the set-point |
| Light | 51 % |
| Tank | 94.2 % |
| Pump | **ON** |

| Model | Output | Ground truth |
|---|---|---|
| M1 demand probability | **0.992 → YES** | 1 ✓ |
| M2 soil at *t*+30 | **37.0 %** | 36.6 % (error 0.4 pp) ✓ |
| M3 | NORMAL | not a fault ✓ |

Note the joint story: high temperature (35 °C) plus low humidity (34 %) gives a large
vapour-pressure deficit, so evapotranspiration is high, so the model is highly confident
demand persists. M2 correctly predicts moisture **rising** to 37 % because the pump is
already running. Point this out — it shows the regressor has learned the irrigation term of
the water balance, not just extrapolated the recent downward trend.

### S3 · Soil sufficiently wet → irrigation stopped

| Channel | Value |
|---|---|
| Temperature | 26 °C |
| Soil moisture | **60.4 %** — just past the stop set-point |
| Light | 1 % (after sunset) |
| Tank | 79.5 % |
| Pump | **OFF** — just switched |

| Model | Output | Ground truth |
|---|---|---|
| M1 demand probability | **0.000 → NO** | 0 ✓ |
| M2 soil at *t*+30 | **59.8 %** | 59.8 % (error 0.0 pp) ✓ |

The controller released the pump at 60.4 %, and the model agrees there is no impending
demand. M2 predicts a slow decline because it is night: light is 1 %, so ET is at its
minimum. The contrast with S2's rising prediction is the clearest single demonstration that
the regressor is physically grounded.

### S4 · Low water tank → pump disabled + alert

| Channel | Value |
|---|---|
| Temperature | 22 °C |
| Soil moisture | **35.7 %** — dry enough to want irrigation |
| Tank | **17.8 %** — below the 20 % interlock |
| Pump | **OFF** |

| Model | Output | Ground truth |
|---|---|---|
| M1 demand probability | **0.064 → NO** | 0 ✓ |
| M2 soil at *t*+30 | **36.7 %** | 34.9 % |

**This is the most interesting scenario in the suite.** The soil is dry, so a naive model
would say YES. The Random Forest says NO with probability 0.064 — because
`agronomic_demand` is defined as demand **conditional on water being available**, and the
model learned the interlock from `water_level_pct` and `water_available` without being told
the rule. The dashboard shows the red "pump held OFF by the low-water interlock" banner.

Expect the question *"why is the model saying no irrigation when the soil is dry?"* — this
is the answer, and it is a strong one.

### S5 · High temperature warning

| Channel | Value |
|---|---|
| Temperature | **36 °C** — above the 35 °C limit |
| Humidity | 31 % |
| Soil moisture | 44.7 % |
| Light | 31 % |
| Tank | 70.0 % |
| Pump | OFF |

| Model | Output | Ground truth |
|---|---|---|
| M1 demand probability | **0.005 → NO** | 0 ✓ |
| M2 soil at *t*+30 | **43.4 %** | 43.2 % (error 0.2 pp) ✓ |

Amber heat-stress banner, but no irrigation action. Correct: at 44.7 % the soil is well
above the depletion line and will only fall ~1.3 pp in the next half hour. **Heat alone is
not an irrigation trigger** — irrigating on air temperature rather than soil water is
exactly the over-watering behaviour the project is meant to prevent. Make that point
explicitly; it is a design decision, not an omission.

### S6 · Abnormal sensor readings → anomaly detected

| Channel | Value |
|---|---|
| Temperature | 25 °C |
| Humidity | 55 % |
| Soil moisture | **61.3 %** |
| Light | 0 % (midnight) |
| Tank | 70.8 % |
| Pump | OFF |

| Model | Output | Ground truth |
|---|---|---|
| M3 score | **+0.0034** (flags above 0) → **ANOMALY** | `drift:soil_moisture_pct` ✓ |
| M2 soil at *t*+30 | 61.7 % | 52.5 % (**error 9.3 pp**) |

A calibration drift is inflating the soil probe. Three things to draw attention to:

1. 61.3 % is not an out-of-range value — a range check would pass it. It is only anomalous
   *in context*: the reading sits at field capacity and is climbing at midnight with the
   pump off and no rain, which the water balance forbids. That is what `hydro_residual` and
   `soil_moisture_pct_dev_360` encode.
2. **M2's error jumps to 9.3 pp**, roughly 11× its normal MAE of 0.86. This is the concrete
   argument for having a trust layer at all: when the input is corrupted, the downstream
   regressor degrades *silently* — it returns a confident wrong number, not an error. M3 is
   what makes that degradation visible.
3. The dashboard therefore shows "verify the probe before acting on the irrigation
   decision" rather than an actuation command.

Note the score is only just above the boundary (+0.0034). Slow drift is detected once it has
accumulated, not at onset — median event latency in the test period is 3 minutes overall but
22 minutes for drift specifically. Say this before you are asked.

---

## Suite C — Negative and robustness tests

Include these; they are what separates a tested system from a demonstrated one.

| ID | Test | Expected | Actual |
|---|---|---|---|
| C1 | Random split instead of chronological | metrics inflate towards 1.0 | run it and quote the number — it is the leakage demonstration |
| C2 | Train M1 on `naive_rule_label` | ≈ 1.0, proving tautology | **0.9974** |
| C3 | M1 vs persistence on the pump-state target | persistence wins | RF F1 0.906 vs persistence **0.921** |
| C4 | M1 in the transition region only | RF wins where it matters | RF F1 **0.847** vs persistence 0.670 |
| C5 | M2 vs persistence | model must win | RMSE 1.94 vs **3.23**, skill 0.638 |
| C6 | M3 with raw features instead of residuals | large degradation | ROC-AUC **0.62** vs 0.88 |
| C7 | M3 vs rolling z-score baseline | model must win | P 0.327/R 0.463 vs **P 0.268/R 0.088** |
| C8 | Blocked TimeSeriesSplit CV | high variance across folds | F1 **0.770 ± 0.305** |
| C9 | Water-balance coefficient recovery | recovers the simulator constant | **+0.0980** vs true 0.100 %/min |

---

## Test summary table for the report

| # | Scenario | Component under test | Result |
|---|---|---|---|
| A1 | Normal | control law, LCD, LEDs | Pass |
| A2 | Dry soil → pump ON | lower set-point | Pass |
| A3 | Wet soil → pump OFF | hysteresis dead band | Pass |
| A4 | Low tank | interlock priority | Pass |
| A5 | High temperature | alert without actuation | Pass |
| A6 | Sensor fault | fail-safe direction | Pass |
| S1 | Normal | M1+M2+M3 joint | Pass |
| S2 | Irrigation demand | M1 recall | Pass |
| S3 | Demand released | M1 specificity, M2 physics | Pass |
| S4 | Water unavailable | learned interlock | Pass |
| S5 | Heat stress | alert without false trigger | Pass |
| S6 | Sensor drift | M3 contextual detection | Pass |
| C1–C9 | Methodology | leakage, baselines, ablations | 9/9 as expected |
