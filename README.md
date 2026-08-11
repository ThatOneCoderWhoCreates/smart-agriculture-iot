# IoT-Based Smart Agriculture System with ML-Driven Irrigation Prediction and Anomaly Detection

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://smartagriculture-using-iot.streamlit.app/)

A complete, runnable implementation: simulated field node → cloud telemetry → dataset →
analytics → three ML models → operations dashboard.

Everything in this repository has been executed. The numbers quoted below are the actual
held-out test results, not placeholders.

---

## 1. What the system does

Six channels are monitored once per minute (temperature, humidity, soil moisture, light,
tank level, pump state). A hysteresis controller on the node irrigates autonomously. In
parallel, three models turn the raw stream into decisions:

| ID | Model | Question it answers | Held-out result |
|----|-------|--------------------|-----------------|
| M1 | Random Forest Classifier | Will the field cross its depletion line within 120 min? | Acc **0.978**, P **0.922**, R **0.843**, F1 **0.881**, ROC-AUC **0.997** |
| M2 | Random Forest Regressor | What will soil moisture be in 30 min? | MAE **0.86 pp**, RMSE **1.94 pp**, R² **0.948** |
| M3 | Isolation Forest | Is this reading physically plausible? | P **0.327**, R **0.463**, F1 **0.383**, ROC-AUC **0.836** |

Baselines each model must beat (and does): persistence F1 **0.842** for M1, the reactive
threshold rule at F1 **0.052** for M1, persistence RMSE **3.23 pp** for M2 (skill score
**0.638**), and a rolling z-score at P **0.268** / R **0.088** for M3.

---

## 2. Architecture

```
        FIELD LAYER                    EDGE LAYER                 NETWORK
 ┌──────────────────────┐      ┌──────────────────────┐      ┌──────────────┐
 │ DHT11   T, RH        │      │ ESP32 / Arduino Uno  │      │              │
 │ Soil probe   θ       ├─────►│  • median-of-5 filter│      │  WiFi 802.11 │
 │ LDR     lux          │ ADC  │  • unit conversion   ├─────►│  HTTPS       │
 │ HC-SR04 tank level   │ GPIO │  • hysteresis control│      │              │
 └──────────────────────┘      │  • 20 s aggregation  │      └──────┬───────┘
             ▲                 └──────────┬───────────┘             │
             │ relay + DC pump            │ Serial CSV              ▼
             └────────────────────────────┘                 ┌──────────────┐
                                                            │  ThingSpeak  │
                                                            │  6 fields    │
                                                            │  time-series │
                                                            └──────┬───────┘
                                                                   │ feeds.csv
   ANALYTICS / ML LAYER                                            ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ 01 generate  → 02 clean + features → 03 train/evaluate → dashboard        │
 │                                                                           │
 │  cleaning        feature store (96 cols)      M1 classifier ──┐           │
 │  • range check   • lags 5/15/30/60            M2 regressor  ──┼─► decision│
 │  • gap-aware     • rates, rolling stats       M3 isolation  ──┘   fusion  │
 │    imputation    • VPD, ET proxy, q                                       │
 │  • flat-run,     • water-balance residual                                 │
 │    monotonicity                                                           │
 └───────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
                          Streamlit control centre
             live values · history · prediction · anomaly · metrics
```

**Control law on the node** (identical in both firmware builds):

```
soil < 35 %  AND tank > 20 %   →  pump ON
soil > 60 %                    →  pump OFF
tank ≤ 20 %                    →  pump OFF + low-water alert   (hard interlock)
temp ≥ 35 °C                   →  high-temperature warning
35 % ≤ soil ≤ 60 %             →  hold current state           (dead band)
```

The dead band plus a 10 s minimum dwell is what stops the relay chattering; a single
threshold would toggle the pump thousands of times a day.

---

## 3. Repository layout

```
smart_agri/
├── arduino/
│   ├── smart_agri_tinkercad/           Arduino Uno, Tinkercad-compatible
│   ├── smart_agri_esp32_thingspeak/    ESP32 + WiFi + ThingSpeak (real hardware)
│   └── wokwi/                          diagram.json + sketch.ino + libraries.txt
├── python/
│   ├── 01_generate_dataset.py          physics-based 21-day campaign
│   ├── 02_preprocess_analyze.py        cleaning, features, EDA, figures
│   ├── 03_train_models.py              M1 / M2 / M3 + evaluation
│   ├── thingspeak_io.py                bulk upload / feed download
│   └── 05_pack_for_deploy.py           gzip runtime data before pushing
├── dashboard/
│   ├── app.py                          Streamlit control centre
│   ├── theme.py                        palette, CSS, instrument components
│   ├── live_engine.py                  stateful field simulator + online features
│   └── live_panel.py                   real-time mode
├── data/                               raw, ground truth, processed, predictions
├── models/                             three .joblib bundles
├── figures/                            13 report-ready plots
├── reports/                            metrics tables (md + json)
└── docs/                               wiring, ThingSpeak, tests, report, PPT, viva
```

---

## 4. Build order (zero to demo)

| Day | Task | Artefact you can show |
|-----|------|----------------------|
| 1 | Build the Tinkercad circuit, flash `smart_agri_tinkercad.ino` | working simulation, Serial CSV, LCD + LEDs |
| 2 | Create the ThingSpeak channel, port to Wokwi ESP32 | live channel with six populated fields |
| 3 | Run `01_generate_dataset.py`, upload with `thingspeak_io.py` | 21-day history visible in ThingSpeak plots |
| 4 | Run `02_preprocess_analyze.py` | descriptive stats, correlations, 7 figures |
| 5 | Run `03_train_models.py` | 3 trained models, 6 evaluation figures, metrics |
| 6 | Run the dashboard, walk the six test scenarios | screen recording for the demo |
| 7 | Write the report and slides from `docs/` | submission |

---

## 5. Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python python/01_generate_dataset.py      # ~20 s
python python/02_preprocess_analyze.py    # ~40 s
python python/03_train_models.py          # ~4 min
streamlit run dashboard/app.py
```

Optional, once you have a channel:

```bash
export TS_CHANNEL_ID=1234567
export TS_WRITE_KEY=XXXXXXXXXXXXXXXX
python python/thingspeak_io.py upload --resample 5min   # 7 bulk calls, ~2 min
python python/thingspeak_io.py download --results 8000
```

---

## 6. Documentation index

| File | Contents |
|------|----------|
| `docs/01_system_architecture.md` | layer-by-layer design, data contract, failure handling |
| `docs/02_hardware_wiring.md` | Tinkercad component list, pin map, wiring tables, substitutions |
| `docs/03_thingspeak_setup.md` | channel creation, field map, rate limits, MATLAB visualisations |
| `docs/04_dataset_and_methodology.md` | the physics model, label engineering, why the split is chronological |
| `docs/05_test_cases.md` | the six required scenarios with exact timestamps and expected outputs |
| `docs/06_report_structure.md` | chapter-by-chapter report skeleton with what goes in each section |
| `docs/07_ppt_structure.md` | 18-slide deck plan with speaker notes |
| `docs/08_viva_qa.md` | 62 questions and answers, including the ones designed to catch you out |
| `docs/09_live_mode.md` | the real-time simulation mode, its controls and its verification |
| `docs/10_wokwi_build_guide.md` | Tinkercad vs Wokwi, and a step-by-step circuit build |
| `docs/11_deployment.md` | putting the dashboard online for free |

---

## 7. Honest limitations

State these yourself before the examiner does — it converts a weakness into evidence of
rigour.

1. **The field data are simulated.** They come from a coupled water-balance / energy-balance
   model, not a real plot. The correlations are real consequences of the model, not injected
   by hand, but the model is still a model. Section 4 of `docs/04` states every equation and
   constant.
2. **M1's target is the controller state 30 min ahead**, so `pump_status` is a strong
   predictor by construction. The ablation without any pump feature is reported
   (F1 drops from 0.906 to the value in `reports/model_metrics.json`) precisely so this is
   visible rather than hidden.
3. **M3 detects contextual faults, not dropouts.** Dropouts are caught deterministically by
   the firmware range check (Layer 1, precision 1.00). Only the contextual faults are
   credited to the ML layer. Slow drift is detected after it accumulates — median event
   latency is reported, and three of fourteen test-period fault events were missed entirely.
4. **Tinkercad cannot reach the internet.** ThingSpeak connectivity is demonstrated in Wokwi
   (ESP32, simulated WiFi stack + IoT gateway) or on real hardware. This is a platform
   limitation, not a design shortcut, and is documented in `docs/02`.
