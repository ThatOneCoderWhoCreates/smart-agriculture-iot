# 07 · Presentation Structure

**18 slides · 12–15 minutes · 5 minutes questions.** Roughly 45 seconds per slide, so one
idea per slide and no paragraphs.

Design rules: dark text on light background, one figure per slide at full width, numbers in
a larger weight than labels, and no slide that requires the audience to read while you talk.

---

### Slide 1 · Title

Project title, your name and register number, course code, supervisor, institution, date.

> *Say:* nothing. Let them read it while you set up.

---

### Slide 2 · The problem in one number

Big centred statistic: **a reactive threshold controller has recall 0.027 against impending
irrigation demand.**

> *Say:* "Conventional soil-moisture control only acts once the crop is already stressed.
> On my dataset, a threshold rule catches under 3 % of the moments when the field is about
> to cross its depletion line. That gap is what this project closes."

This is the strongest possible opening because it is your own result, not a citation.

---

### Slide 3 · Objectives

Six bullets, three words each. Sensing · Cloud · Dataset · Predict demand · Forecast
moisture · Detect faults.

---

### Slide 4 · System architecture

The layer diagram (`docs/01 §1`), full width.

> *Say:* "Six channels, edge control, cloud telemetry, and a three-model analytics layer.
> The one property to notice: the control loop does not depend on the cloud. If WiFi drops,
> the field keeps irrigating correctly."

---

### Slide 5 · Hardware and circuit

Tinkercad screenshot left, component table right.

> *Say:* include the substitution point proactively — "Tinkercad ships no DHT11 and no DHT
> library, so temperature uses a TMP36 and humidity a potentiometer, following Autodesk's
> published substitution guidance. The control logic is byte-identical between this build
> and the ESP32 build that talks to the cloud."

Raising this yourself removes it from the examiner's question list.

---

### Slide 6 · Control law

The pseudocode block plus the four-state diagram.

> *Say:* "Hysteresis, not a single threshold. The 35–60 % dead band gives 18 irrigation
> events across 21 days. A single set-point would toggle the relay thousands of times,
> past its mechanical life. And the low-water interlock is evaluated first — it overrides
> irrigation demand, because running a pump dry destroys it in minutes."

---

### Slide 7 · Cloud telemetry

ThingSpeak channel screenshot with all six fields populated.

> *Say:* "Free channels accept one update per 15 seconds, so the node samples at 2 s and
> publishes a 20-second mean. Averaging ten samples also cuts ADC noise by root-ten, so the
> rate limit ended up improving the data."

---

### Slide 8 · The dataset is physics, not random numbers

The governing equation, and Figure 02 (the 3-day control-loop zoom).

> *Say:* "Soil moisture is integrated from a water balance: irrigation plus rain, minus
> evapotranspiration and drainage. Evapotranspiration is driven by vapour-pressure deficit
> and solar radiation. Nothing is drawn from a random number generator except the noise."

---

### Slide 9 · Evidence the physics is self-consistent

One box, centred:

> Analytics least-squares fit on week 1 recovers a pump recharge coefficient of
> **+0.0980 %/min**. The simulator's true constant is **0.100 %/min**.

> *Say:* "The preprocessing stage was never told the simulator's parameters. It rediscovered
> one of them to within 2 % from the data alone."

This is the slide that converts scepticism about simulated data into confidence.

---

### Slide 10 · Correlations that emerge, not imposed

Figure 03, the heatmap. Annotate three cells.

> *Say:* "Temperature and humidity at −0.93 — that is the Magnus saturation curve, not a
> parameter I set. Spearman is stronger than Pearson for soil moisture, which tells you the
> relationship is monotone but non-linear. That is the argument for tree-based models."

---

### Slide 11 · Label engineering — the slide that wins marks

Three rows:

| Target | Result | Verdict |
|---|---|---|
| Rule restated | acc 0.997 | tautology — rejected |
| Pump state at *t*+30 | RF F1 0.906 vs persistence **0.921** | baseline wins — rejected |
| Agronomic demand at *t*+120 | RF F1 **0.881** vs rule **0.052** | adopted |

> *Say:* "I built three targets. The first is a restatement of the controller rule — the
> forest scores 0.997 and learns nothing. The second looked good until I checked a trivial
> persistence baseline, which beat it. I'm reporting that negative result deliberately. The
> third is agronomically meaningful and excludes every pump-state feature, so the model has
> to infer demand from the micro-climate."

Nothing else on the slide. Let it land.

---

### Slide 12 · M1 · Classification results

Confusion matrix and ROC curve (Figure 08), plus the baseline table.

Accuracy **0.978** · Precision **0.922** · Recall **0.843** · F1 **0.881** · ROC-AUC **0.997**

> *Say:* "Recall 0.84 against a threshold-rule baseline of 0.027. The 129 false negatives
> concentrate near the depletion boundary, which is the expected failure location."

---

### Slide 13 · M2 · Forecasting results

Figure 10, actual vs predicted.

MAE **0.86 pp** · RMSE **1.94 pp** · R² **0.948** · skill score vs persistence **0.637**

> *Say:* "Persistence — assuming no change over 30 minutes — gives RMSE 3.23. The model
> removes 64 % of that error variance. Worst case is 14 pp, at pump-start transients."

---

### Slide 14 · M3 · Anomaly detection and the ablation

Figure 12, plus two ablation bars: raw features **0.62** → residual features **0.88**, then
centred window **0.879** → trailing window **0.836** (the deployable one).

> *Say:* "Isolation Forest scores low-density regions. Fed raw sensor values it spent its
> budget flagging normal midday peaks, because the diurnal envelope is itself a legitimate
> sparse tail. Replacing levels with residuals took ROC-AUC from 0.62 to 0.88. Then I found
> those residuals used a centred window, which a live node cannot compute — so I switched to
> a trailing window and retrained. That cost four points of AUC. I shipped the lower number,
> because it is the one that deploys."

---

### Slide 15 · Layered detection, honestly reported

Recall by fault family: spike 1.00 · stuck 0.71 · drift 0.28 · dropout 0.00.

> *Say:* "Dropouts are zero deliberately. A −999 is caught by a range check in firmware at
> precision 1.0 — it would be dishonest to credit machine learning with that. Only
> contextual faults are attributed to the ML layer. At event level, 11 of 14 fault events
> were caught, median latency 3 minutes."

---

### Slide 16 · Live demonstration

Switch to the dashboard. Walk **S1 → S2 → S4 → S6** in that order — normal, then demand,
then the interlock, then the anomaly. Skip S3 and S5 if time is short.

Spend most of the time on **S4**: soil at 35.7 % but the model says NO with probability
0.064, because the tank is at 17.8 %. The model learned the interlock from the data.

Have a screen recording as a fallback. Live demos fail.

---

### Slide 17 · Limitations and future work

Two columns. Limitations: simulated data; drift latency; centred windows are an offline
assumption. Future: field validation with a TDR reference; weather-forecast integration;
on-device inference.

> *Say:* "Naming these is not weakness. The single largest remaining error source in M2 is
> unforecast rainfall, and a weather API would address it directly."

---

### Slide 18 · Conclusion

Three numbers, large: **0.881 F1 · 0.948 R² · 0.836 ROC-AUC**, and one sentence on what the
system does. Then thank you and questions.

---

## Backup slides (do not present; keep after slide 18)

| # | Content |
|---|---|
| B1 | Full pin map, both boards |
| B2 | Complete feature list, 96 columns by group |
| B3 | Feature importance, Gini vs permutation |
| B4 | TimeSeriesSplit fold-by-fold results and why variance is high |
| B5 | Why Random Forest rather than SVM / XGBoost / LSTM |
| B6 | ThingSpeak rate limits and bulk-update constraints |
| B7 | The random-split leakage demonstration |
| B8 | Relay driving circuit with the flyback diode |

Having B5 and B7 ready and pulling them up mid-answer is disproportionately impressive.

---

## Delivery notes

- Rehearse **out loud**, timed, at least three times. Silent rehearsal always runs short.
- Never read a slide aloud. If it is on the screen, add to it instead.
- When you do not know something: "I did not test that — my expectation is X, and the way
  to check it would be Y." That answer scores; bluffing does not.
- Have the code open in a second window. Being able to jump to the exact function when
  asked is worth more than any slide.
