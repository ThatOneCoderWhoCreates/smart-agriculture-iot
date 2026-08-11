# 09 · Live Simulation Mode

The dashboard has two modes, selected at the top of the sidebar.

**Appearance** is a separate control at the top of the sidebar: Light, Dark, or Match
system. It restyles the whole app including the Plotly panels; nothing is a filter applied
over the other mode. "Match system" reads the theme Streamlit is actually rendering, so it
follows your macOS setting.

| Mode | What it is | Use it for |
|---|---|---|
| **Recorded playback** | replays the held-out test period; a cursor picks the minute | reporting results — every number is on data the models never saw |
| **Live simulation** | integrates the field forward one simulated minute per tick and re-scores all three models | the demo — interactive, and you can break things on purpose |

---

## 1. Why a live mode needs state

The obvious version of "take three inputs and do analytics on them" does not work, and
being able to explain why is worth marks on its own.

M1 uses 33 features and M2 uses 37. Most are **history**: `soil_lag_60`, `soil_ma_120`,
`soil_rate_15`, `temp_std_60`, `pump_on_last_60`. Three instantaneous slider values give you
five of the thirty-seven. Everything else would have to be invented, and the model would
then print a confident probability derived from fabricated inputs — worse than showing
nothing, because it looks authoritative.

So the live mode keeps state, in two objects:

| Object | File | Responsibility |
|---|---|---|
| `FieldSimulator` | `dashboard/live_engine.py` | integrates the same water balance and energy balance as `01_generate_dataset.py`, one simulated minute per `step()`, and runs the same hysteresis controller as the firmware |
| `FeatureBuilder` | `dashboard/live_engine.py` | keeps a 400-minute rolling buffer and derives the full feature row online, so every lag and rolling statistic is genuine |

On start-up the simulator runs **420 minutes headless** so the buffer is full before the
first prediction. The models are never asked to score a partially-warm buffer.

---

## 2. Verification: the online features are the same features

This is the claim that makes the live mode admissible as evidence rather than decoration. It
was tested by replaying recorded raw telemetry through `FeatureBuilder` and comparing against
the offline pipeline row by row:

| Model | Agreement |
|---|---|
| M1 predicted probability | max abs difference **0.114** |
| M2 predicted soil moisture | max abs difference **0.196 pp** |
| M3 anomaly flag | **99.83 %** of samples agree; score correlation **0.993** |

The residual difference comes from one genuine and unavoidable online/offline distinction:
offline, a dropout gap is filled by time interpolation, which needs the samples on both
sides of the gap. A live node has only the past, so it holds the last valid reading. That
propagates a small difference into the lag features for a few minutes after each dropout.
Say this if asked why the agreement is not exactly 100 %.

Reproduce it yourself — the check is worth having in the appendix:

```python
from live_engine import FeatureBuilder
fb = FeatureBuilder()
for row in raw_readings:            # sensor_data_raw.csv
    fb.push(row)
    if fb.ready():
        online = fb.features()      # compare against processed_dataset.csv
```

### The change this forced

The first version of the pipeline computed the 6-hour baselines (`*_dev_360`, `q_dev_360`)
with a **centred** window. That scored better — ROC-AUC 0.879, F1 0.453 — but a centred
window needs future samples, so no live node can compute it. Building the live mode exposed
this: the online features and the trained model disagreed so badly that the detector flagged
77 % of samples.

Stage 2 was changed to a **trailing** window and M3 retrained. The cost is real and is
reported: ROC-AUC 0.836, F1 0.383. That is roughly 4 points of AUC paid for deployability,
and the shipped model is the deployable one.

This is a good story to tell in the viva, because it is a case where building the demo
found a methodological flaw in the modelling.

---

## 3. Controls

The sidebar deliberately separates two groups, because the distinction between them is
exactly what the anomaly detector exists to make.

### Field conditions — change the physical state

The water balance and the controller both respond, because these act on the true state
before the sensor model runs.

| Control | Range | Effect |
|---|---|---|
| Temperature forcing | −8 … +10 °C | added to true air temperature; raises VPD, raises ET, accelerates drying |
| Humidity forcing | −25 … +25 % RH | added to true relative humidity; lowers VPD when raised |
| Hold soil moisture at | 5 … 72 % | clamps true root-zone moisture each tick |
| Hold tank level at | 0 … 100 % | clamps true tank level; use this to trigger the interlock |
| Pump | Automatic / Force ON / Force OFF | overrides the controller |
| Refill tank | button | ramps the tank back to 95 % |
| Make it rain | button | 45-minute rain event |

### Sensor corruption — change only the reported value

The controller keeps seeing the truth, so the pump behaves correctly while the *reading* is
wrong. This is the whole point of M3.

| Control | Effect |
|---|---|
| Soil probe bias | offset applied to the reported soil moisture only |
| Inject fault | one of `spike`, `stuck`, `drift`, `dropout`, `phantom_wet`, `tank_leak`, for a chosen duration |

### Detector operating point

| Setting | Boundary | Flag rate |
|---|---|---|
| **F1-optimal** (default) | tuned threshold from the sweep, top 9 % of scores | higher recall on slow faults |
| **Conservative** | the model's own boundary, `decision_function < 0` | matches the headline metrics in the report |

---

## 4. Measured live behaviour

From a headless run of the engine, F1-optimal operating point, each fault injected after
200 minutes of settling:

| Fault | Recall during the window | First detection | Caught by Layer 1? |
|---|---|---|---|
| `spike` | 1.00 | 0 min | no |
| `stuck` | 0.97 | 2 min | no |
| `drift` | 0.53 | 22 min | no |
| `tank_leak` | 0.70 | 15 min | no |
| `phantom_wet` | 0.45 | 9 min | no |
| `dropout` | 0.00 | — | **yes** (validity gate, precision 1.00) |

False-positive flag rate on 900 clean simulated minutes: **0.006**.

Note this is *lower* than the 0.073 flag rate on the recorded test set, and the reason is
worth stating: a short live run explores a narrow, benign slice of the state space, whereas
the recorded campaign contains heatwaves, rain, and the low-water stress episode. Live
false-positive rates are therefore optimistic, and slow-fault sensitivity correspondingly
lower. **Quote the recorded-playback numbers as the results; use live mode to demonstrate
behaviour, not to generate metrics.**

---

## 5. Out-of-distribution guard

Push the temperature forcing to +10 °C and the field reaches 48 °C, well outside the
18–40 °C the models were trained on. The dashboard detects this and shows an explicit
warning instead of quietly printing a prediction:

> **Outside the training envelope** — temperature_c, humidity_pct. The models never saw this
> region, so the predictions below are extrapolation and should not be quoted as results.

The envelope is the 1st–99th percentile of the training period, hard-coded in
`TRAIN_RANGE` in `live_engine.py`:

| Channel | Envelope |
|---|---|
| Temperature | 18 – 40 °C |
| Humidity | 22 – 95 % |
| Soil moisture | 16.5 – 67.5 % |
| Light | 0 – 99.6 % |
| Water level | 18 – 95.8 % |

Demonstrating this deliberately is a strong move: it shows you know that a model asked to
extrapolate will still return a number, and that the responsibility for noticing sits with
the system, not the model.

---

## 6. Demo script for the viva

Five minutes, in this order. Set speed to 15 sim-min/s unless told otherwise.

1. **Baseline.** Press Run. Let it settle. All pills green, soil drifting down slowly, M1
   probability near zero. *"The field is drying at about 0.02 percentage points a minute,
   which is the evapotranspiration term."*
2. **Force irrigation.** Tick "Hold soil moisture at", drag to 30 %. The pump starts within
   one tick, the yellow pill flips to IRRIGATING, and M2's dotted prediction line turns
   upward. Untick and let the controller refill to 60 % and release. *"That is the hysteresis
   loop — it will not stop until 60 %, not 35 %."*
3. **The interlock.** Tick "Hold tank level at", drag to 15 %. Hold soil at 30 % again. The
   pump stays OFF despite dry soil, and M1's probability stays low. *"The model learned that
   demand is conditional on water being available — I never encoded that rule into it."*
   Press Refill tank and watch it resume.
4. **Heat.** Drag temperature forcing to +6 °C. Watch VPD-driven drying accelerate and the
   heat-stress pill turn amber, but no irrigation trigger. Then push to +10 °C to show the
   out-of-distribution warning appear.
5. **The trust layer.** Set speed to 5. Inject a `drift` fault for 60 minutes. Watch the
   anomaly score climb across the red line ~20 minutes in while the soil trace keeps looking
   plausible. *"No individual value is out of range. It is only impossible in context."*
   Then set the soil probe bias to +25 and point out that the pump behaviour does not change
   — the controller sees the truth, only the reading is corrupt.

Have a screen recording as a fallback. Live demos fail.

---

## 7. Performance

| Operation | Cost |
|---|---|
| One simulated minute (physics only) | ~0.1 ms |
| Feature build from the buffer | ~2 ms |
| Scoring all three models | ~145 ms |
| One UI tick at 60 sim-min/s | ~108 ms |

Only the minute the operator actually sees is scored; intermediate minutes are buffered so
they still feed every lag and rolling window. Without that, a 60 sim-min tick would take
almost nine seconds and the interface would stall.
