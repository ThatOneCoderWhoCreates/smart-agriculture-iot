# 04 · Dataset, Physics Model and ML Methodology

This is the chapter that decides whether the project reads as engineering or as a script
that called `.fit()`. Every constant below is in `01_generate_dataset.py`; quote them.

---

## 1. Why the data are simulated, and how to say so

A real 21-day campaign needs a real plot, a real pump and three weeks. What matters
academically is not that the data came from soil, but that **the statistical structure the
models exploit is a consequence of stated physics rather than something injected by hand**.

The honest framing, which you should put in the report abstract and repeat in the viva:

> The field data are produced by a coupled water-balance / energy-balance simulator. Sensor
> noise, ADC quantisation, and six classes of hardware fault are then applied on top. No
> correlation in the dataset is specified directly; every one emerges from the governing
> equations.

An independent check that this worked: `02_preprocess_analyze.py` least-squares fits the
30-minute soil-moisture change against pump run-time on the **first week only**, and
recovers a pump recharge coefficient of **+0.0980 %/min**. The simulator's true constant is
**0.100 %/min**. The analytics layer rediscovered a physical parameter it was never told,
to within 2 %.

---

## 2. The simulator

### 2.1 Governing equation

Root-zone water balance, integrated at Δt = 1 min:

```
dθ/dt = I(t) + R(t) − ET(t) − D(θ)
```

| Term | Meaning | Model |
|---|---|---|
| θ | root-zone moisture (%) | state, clipped to [4, 72] |
| I | irrigation recharge | `0.100 %/min` while pump ON |
| R | rainfall infiltration | Poisson events, mean 3.2 d apart, 20–95 min, peak 0.10–0.45 %/min |
| ET | evapotranspiration | FAO-56 flavoured, §2.3 |
| D | gravitational drainage | `0.060 × max(θ − θ_FC, 0)`, θ_FC = 62 % |

### 2.2 Atmospheric drivers

**Solar irradiance** — clear-sky sinusoid between sunrise 06:12 and sunset 18:36, raised to
the power 1.15, attenuated by cloud:

```
clear_sky = sin(π(h − 6.2)/12.4)^1.15
irradiance = clear_sky × (1 − 0.78 × cloud)
```

Cloud cover is an **Ornstein–Uhlenbeck** process (mean-reverting), not white noise — real
cloudiness is autocorrelated over hours. Rain events force cloud toward 0.9.

**Air temperature** — seasonal baseline + diurnal cosine peaking at 15:00 + a direct
irradiance term + OU weather wander + two engineered heatwave days:

```
T = 27.5 + 1.8·sin(2πd/30) + 6.4·(−cos(2π(h−3.2)/24)) + 4.1·irradiance − 1.6·cloud + w(t)
```

The 3.2 h offset is the thermal lag of the ground — temperature peaks about two hours after
solar noon. Observed range: **14.4 – 41.8 °C**.

**Humidity** — *not* generated directly. Specific humidity `q` (kg/kg) is an OU process,
and relative humidity is derived through the Magnus–Tetens saturation curve:

```
e_s(T) = 6.112 · exp(17.67·T / (T + 243.5))        [hPa]
e      = qP/(0.622 + q),   P = 1000 hPa
RH     = 100 · e / e_s(T)
```

This is why temperature and humidity come out at **r = −0.931** in the dataset. Nobody
specified that number; it falls out of the fact that warm air holds more vapour. If an
examiner asks "isn't −0.93 suspiciously strong?", this is the answer.

### 2.3 Evapotranspiration

```
VPD  = e_s(T) · (1 − RH/100)                        vapour-pressure deficit
ET₀  = 0.052 · (0.22 + 0.78·irradiance)
              · (1 + 0.030·(T − 25))
              · (0.35 + 0.65·min(VPD/22, 1.6))
Ks   = clip((θ − θ_WP) / (0.45·(θ_FC − θ_WP)), 0, 1)   soil-water stress factor
ET   = ET₀ · Ks
```

`Ks` is the FAO-56 water-stress coefficient: a dry soil transpires less because the plant
closes stomata. Without it the soil would dry linearly to zero, which is physically wrong
and would make the regression task trivially easy.

### 2.4 Tank and controller

- Pump draws **0.047 %/min** of tank volume; tank evaporates 0.0009 %/min.
- Scheduled top-up at 05:00 if below 55 %, refilling at 3 %/min to 95 %.
- **Refills are deliberately skipped on days 11–14** to produce the low-water scenario. The
  tank bottoms out at **18.1 %**, the interlock fires for **2,137 minutes**, and soil
  moisture falls to **15.8 %** because irrigation is blocked. That single design choice
  generates test scenario S4 and a visible stress episode in the plots.

### 2.5 Sensor model

Physics → what the microcontroller actually reads:

| Channel | Noise | Quantisation |
|---|---|---|
| Temperature | σ = 0.35 °C | rounded to 1 °C (DHT11 resolution) |
| Humidity | σ = 1.4 % | rounded to 1 % |
| Soil moisture | σ = 0.55 % | 10-bit ADC over 0–100 % |
| Light | σ = 0.8 % | 10-bit ADC |
| Water level | σ = 0.30 cm on the range | 0.1 cm, then geometric conversion |

Modelling the DHT11's integer resolution matters: it is the reason `temperature_c_flat_run`
can be legitimately long at night, which in turn is why that feature alone does not
identify a stuck sensor.

### 2.6 Injected faults

Fixed schedule so every failure mode is represented — an opportunistic random loop starves
the rare classes. **1,688 anomalous samples, 5.58 % of the campaign.**

| Class | Events | Duration | Signature |
|---|---|---|---|
| `spike` | 18 | 1–5 min | 2.5–5.5σ transient, one channel |
| `dropout` | 14 | 3–29 min | value replaced by −999 sentinel |
| `stuck` | 8 | 30–79 min | reading latched at its entry value |
| `drift` | 4 | 100–169 min | linear ramp of ±12–26 units |
| `phantom_wet` | 5 | 20–59 min | soil rises 16–30 pp with pump OFF and no rain |
| `tank_leak` | 4 | 45–104 min | level falls 15–32 pp with pump OFF |

The last two are **contextual anomalies**: every individual value is inside its normal
range, and only the joint physics is violated. They are the reason a univariate threshold
detector is not sufficient, and the reason the feature set includes water-balance residuals.

---

## 3. Preprocessing

| Step | Rule | Result on this dataset |
|---|---|---|
| Validity gate | `−999` sentinel or outside the physical range → NaN | **220 readings** removed |
| Grid check | reindex to a strict 1-min grid | 0 missing timestamps |
| Imputation | time-interpolation for gaps ≤ 15 min; forward-fill + explicit flag beyond | 0 residual NaN |
| Smoothing | median-5, **for analytics plots only** | ML sees the unsmoothed signal |

That last row matters. Smoothing before anomaly detection destroys exactly the spikes you
are trying to detect. The smoothed columns are suffixed `_smooth` and are never fed to M3.

---

## 4. Feature engineering — 96 columns

Grouped by what they physically represent:

| Group | Examples | Why |
|---|---|---|
| Raw | 5 sensor channels | baseline |
| Time | `hour_sin`, `hour_cos`, `minute_of_day`, `is_daytime` | cyclic encoding, so 23:59 and 00:01 are adjacent |
| Lags | `soil_lag_{5,15,30,60}`, `temp_lag_{15,30}` | the system has memory |
| Rates | `soil_rate_15`, `soil_rate_60`, `water_rate_30` | drying **velocity** is the predictive quantity, not level |
| Rolling | `soil_ma_{30,120}`, `temp_std_60` | context |
| Physics | `vpd_hpa`, `et_proxy`, `heat_index_proxy`, `deficit_from_target` | domain knowledge injected as features |
| Fault-facing | `*_flat_run`, `*_dev_360`, `*_mono60`, `q_dev_360`, `hydro_residual`, `tank_residual` | for M3 only |

Four of these deserve their own paragraph in the report because they are the difference
between a working and a non-working anomaly detector:

- **`*_flat_run`** — consecutive minutes with zero change. A latched sensor is perfectly
  normal in level and normal in 60-min standard deviation (because most fault windows are
  shorter than the window) but has an impossible run length.
- **`*_dev_360`** — value minus its own centred 6-hour median. Catches drift after it
  accumulates.
- **`*_mono60`** — mean sign of the last 60 first-differences, i.e. how one-directional the
  last hour was. Real weather reverses; a calibration ramp does not. Adding this raised
  drift recall from 0.17 to 0.47.
- **`q_dev_360`** — deviation of *specific* humidity from its 6-hour median. Relative
  humidity swings 40 points a day purely because temperature moves; `q` does not. A drifting
  RH sensor is invisible in RH space and obvious in `q` space.

**Strict causality:** every feature is computable at time *t* from data at or before *t*.
Only targets look forward. Centred rolling windows (`_dev_360`, `_mono60` uses trailing) are
the one exception — they are used for **offline** fault forensics, and the report should say
that an online deployment would use a trailing window with a corresponding detection delay.

---

## 5. Label engineering — the part examiners attack

Three candidate targets were built. Only one is a real learning problem, and the project
reports all three.

### 5.1 `naive_rule_label` — the tautology (rejected)

`soil < 35 AND tank > 20`, i.e. a restatement of the controller rule using the same inputs
the controller uses. A Random Forest scores **0.9974** on it. This is not learning; it is
the model memorising an `if` statement. It is reported *as a control* to demonstrate the
trap, not as a result.

### 5.2 `irrigation_required` = pump state at *t*+30 min (rejected, reported as a negative result)

A genuinely forward-looking target. The RF gets accuracy **0.9610**, F1 **0.9063** —
which looks good until you compute the **persistence baseline** ("assume the pump state does
not change"), which gets accuracy **0.9652**, F1 **0.9212**.

**The trivial baseline beats the Random Forest.** The reason is structural: with
`pump_status` in the feature set, the target is close to a lagged copy of an input, so
"predict no change" is already near-optimal, and 97 % of minutes are steady-state.

The one place the model does add value is the transition region (within ±45 min of a real
pump switch, n = 910): **RF F1 0.847 vs persistence F1 0.670**. That is the honest reading —
the forest is better exactly where the decision is hard and irrelevant everywhere else,
and aggregate metrics hide this.

Publishing this negative result is worth more than hiding it. It also pre-empts the single
most dangerous viva question: *"did you check a trivial baseline?"*

### 5.3 `agronomic_demand` — the adopted target

> Will root-zone moisture cross the 35 % management-allowed-depletion line within the next
> **120 minutes** under a no-irrigation continuation, given that water is available?

Computed inside the simulator from the instantaneous ET and drainage rates:

```
θ_proj = θ − 120·(ET + D)  + 120·R
label  = (θ_proj < 35) AND (tank > 20)
```

Positive rate **15.4 %**. Critically, the feature set for M1 **excludes every pump-state
variable** (33 features, not 37), so the model must infer demand from micro-climate and soil
dynamics rather than reading it off the actuator.

This target is defensible because it is (a) forward-looking, (b) agronomically meaningful —
MAD is a standard irrigation-scheduling concept, (c) not computable from any single input,
and (d) it beats its baselines by a wide margin (§7).

### 5.4 Regression target

`soil_moisture_future_30` — the actual measured soil moisture 30 minutes ahead. No
counterfactual, no engineering; just a shift.

---

## 6. Validation protocol

**Chronological split, no shuffling.**

| Split | Days | Rows |
|---|---|---|
| Train | 0–14 | 21,540 |
| Test | 15–20 | 8,610 |

This is non-negotiable for this data and you must be able to say why: consecutive minutes
of a 1-minute series are near-duplicates (soil moisture autocorrelation at lag 1 exceeds
0.999). A random `train_test_split` puts minute *t* in train and minute *t+1* in test, so
the model is scored on rows it has effectively already seen. Reported accuracy would be
inflated to near 1.0 and would be meaningless.

Additionally: `TimeSeriesSplit(n_splits=5)` blocked cross-validation is reported
(F1 mean **0.770**, std **0.305**). The large standard deviation is itself informative — the
early folds contain very few positives, so it reflects non-stationarity across the campaign
rather than model instability, and the report should say so rather than quote the mean alone.

---

## 7. Results

### M1 — Random Forest Classifier, `agronomic_demand`

400 trees, `max_depth=18`, `min_samples_leaf=4`, `class_weight='balanced_subsample'`,
33 features, OOB **0.9968**.

| | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| NO (0) | 0.9836 | 0.9924 | 0.9880 | 7,787 |
| YES (1) | 0.9216 | 0.8433 | 0.8807 | 823 |
| **Accuracy** | | | **0.9782** | 8,610 |

ROC-AUC **0.9970**. Confusion matrix `[[7728, 59], [129, 694]]`.

| Baseline | Accuracy | F1 |
|---|---|---|
| Current-threshold rule (reactive controller) | 0.9070 | **0.0521** |
| Logistic regression, same features | 0.9159 | 0.6935 |
| **Random Forest** | **0.9782** | **0.8807** |

The threshold rule's F1 of 0.05 is the headline finding: a purely reactive controller has
recall **0.027** against genuine impending demand, because by definition it only fires once
the soil has *already* crossed the line. The whole value proposition of the ML layer is in
that gap.

### M2 — Random Forest Regressor, soil moisture at *t*+30

300 trees, `max_depth=20`, `min_samples_leaf=8`, `max_features=0.5`, 37 features.

| Metric | Model | Persistence | Linear extrapolation |
|---|---|---|---|
| MAE (pp) | **0.858** | 1.496 | 1.704 |
| RMSE (pp) | **1.942** | 3.226 | 4.549 |
| R² | **0.9480** | 0.8564 | — |

Skill score vs persistence = **0.638** (i.e. 64 % of the baseline's error variance
removed). MAPE **1.88 %**; **81.9 %** of predictions within 1 pp, **91.0 %** within 2 pp;
worst-case absolute error **14.1 pp** — which occurs at pump-start transients and should be
stated, not buried.

Top importances: `deficit_from_target` (0.359), `soil_moisture_pct` (0.274),
`soil_ma_30` (0.117), `soil_lag_5` (0.114), `soil_lag_15` (0.074). The model is dominated by
recent soil state, which is physically correct for a 30-minute horizon, and the atmospheric
terms contribute at the margin.

### M3 — Isolation Forest

500 trees, `max_samples=1024`, `contamination=0.05`, RobustScaler, **16 residual features**.

| | Precision | Recall | F1 |
|---|---|---|---|
| Anomaly class | 0.3265 | 0.4629 | 0.3829 |

ROC-AUC **0.8360**, average precision **0.2299**, confusion matrix `[[7740, 425], [239, 206]]`.

**Ablation 1 — the feature view.** Feeding the detector raw sensor levels gave ROC-AUC
**0.62**. Isolation Forest scores low-density regions, and the normal diurnal envelope —
midday peaks, midnight troughs — *is itself* a large legitimate low-density tail, so the
detector spent its budget flagging normal afternoons. Replacing raw levels with residuals
("how far is this from what the physics and recent history allow") lifted ROC-AUC to
**0.88**. Report both numbers.

**Ablation 2 — the price of deployability.** The residual features were first computed with
a **centred** 6-hour window, scoring ROC-AUC **0.879** / F1 **0.453**. A centred window
needs future samples, so a detector trained on it cannot run on a live node. Switching to a
**trailing** window and retraining costs about 4 points of AUC and 7 points of F1 —
**0.836** / **0.383** — and that is the version shipped, because it is the version that
actually deploys. Making this trade explicit, with the number attached, is a stronger result
than quoting the higher score and never mentioning it could not be fielded.

Recall by fault family:

| Family | Recall | Comment |
|---|---|---|
| `spike` | **1.000** | large, instantaneous, trivially isolated |
| `stuck` | 0.708 | `flat_run` catches it once the run is long enough |
| `drift` | 0.282 | only detectable after the ramp accumulates |
| `dropout` | 0.000 | **by design** — see below |

**Layered detection.** Dropouts are caught deterministically by the firmware/preprocessing
range check (Layer 1: precision **1.000** on dropouts). It would be dishonest to credit
machine learning with catching a `−999`. Crediting only Layer 2 with contextual faults gives
F1 **0.392**, ROC-AUC **0.870**; the combined Layer 1 + Layer 2 stack gives precision
**0.353**, recall **0.521**, F1 **0.421**.

**Event-level view**, which is what an operator actually experiences: **11 of 14** fault
events in the test period were detected, median detection latency **3 minutes**. Sample-level
recall of 0.46 and event-level detection of 0.79 are both true; quote both, because the
sample metric penalises the model for the first twenty minutes of a drift that it does
eventually catch.

**Operating point.** The default decision boundary is the model's own
(`decision_function < 0`, flagging 7.3 % of samples). A threshold sweep finds the F1-optimal
point at the top **9 %** of scores, giving F1 **0.400**. The dashboard exposes both.

**Baseline:** the rolling z-score detector from Stage 2 achieves precision **0.268**,
recall **0.088**. Isolation Forest is roughly 1.2× the precision at 5× the recall.
