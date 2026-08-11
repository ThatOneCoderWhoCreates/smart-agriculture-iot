# 06 · Project Report Structure

Target: **55–70 pages** including figures and appendices. Below, each section lists what
goes in it and which artefact supplies the content, so you are never writing from a blank
page.

Standard front matter first: title page, certificate, declaration, acknowledgement,
abstract, table of contents, list of figures, list of tables, list of abbreviations.

**Abstract (≈250 words)** — state the problem, the six-channel node, the hysteresis
controller, the three models, and *three numbers*: M1 F1 0.881, M2 R² 0.948, M3 ROC-AUC 0.836. Abstracts without numbers read as proposals.

---

## Chapter 1 · Introduction (5–6 pp)

| Section | Content |
|---|---|
| 1.1 Background | Agriculture consumes ~70 % of global freshwater; irrigation scheduling is usually calendar-based, not state-based |
| 1.2 Motivation | Reactive threshold control irrigates only *after* the crop is already water-stressed — quantify this with your own result: the threshold rule has recall **0.027** against impending demand |
| 1.3 Problem statement | One paragraph, no hedging: predict irrigation demand before the depletion line is crossed, and detect sensor faults that would corrupt that prediction |
| 1.4 Objectives | Six numbered, each one testable |
| 1.5 Scope and limitations | Say here that the field data are simulated, and why that is methodologically acceptable (`docs/04 §1`) |
| 1.6 Organisation of the report | |

Objectives, phrased so each maps to a chapter and a result:

1. Design a six-channel sensing node with autonomous hysteresis irrigation control.
2. Establish a cloud telemetry path with time-series visualisation.
3. Generate a physically consistent 21-day dataset with realistic sensor noise and six
   classes of injected hardware fault.
4. Predict agronomic irrigation demand 120 minutes ahead (classification).
5. Forecast root-zone soil moisture 30 minutes ahead (regression).
6. Detect anomalous sensor and field states without labelled fault data (unsupervised).

---

## Chapter 2 · Literature Survey (7–9 pp)

Organise by **theme, not by paper**. A table of "Author / Year / Method / Dataset /
Result / Limitation" for 15–20 papers, then 2–3 pages of synthesis.

| Theme | What to cover |
|---|---|
| 2.1 IoT in precision agriculture | node architectures, LoRa vs WiFi vs NB-IoT, power budgets |
| 2.2 Soil moisture sensing | resistive vs capacitive vs TDR; why capacitive is standard now |
| 2.3 Irrigation scheduling | FAO-56 reference ET, crop coefficients, management-allowed depletion |
| 2.4 ML for irrigation prediction | RF, SVM, LSTM comparisons; note that most papers report accuracy without a persistence baseline — this is your gap |
| 2.5 Soil moisture forecasting | horizons, features, typical RMSE (1–4 % VWC is the published range; yours is 1.94) |
| 2.6 Anomaly detection in sensor networks | Isolation Forest, One-Class SVM, LOF, autoencoders; point/contextual/collective taxonomy |
| 2.7 Research gap | Three sentences. Most work reports rule-replicating labels and omits trivial baselines; few separate deterministic validity checks from learned anomaly detection |

The research gap paragraph is the one the examiner reads. Make it specific to what you
actually did differently.

---

## Chapter 3 · System Analysis and Design (8–10 pp)

Source: `docs/01_system_architecture.md`.

- 3.1 Requirements — functional (FR1–FR8) and non-functional (latency, availability,
  fail-safe behaviour) in a numbered table.
- 3.2 Feasibility — technical, economic (BOM cost table), operational.
- 3.3 System architecture — **Figure 3.1**, the layer diagram from `docs/01 §1`.
- 3.4 Data flow — **Figure 3.2**, DFD level 0 and level 1 from `docs/01 §2`.
- 3.5 Data contract — the telemetry frame table with units, ranges and sentinels.
- 3.6 Control law — the pseudocode block plus **Figure 3.3**, a state-transition diagram
  with four states (IDLE, IRRIGATING, INHIBITED, FAULT).
- 3.7 Design decisions and justification — the three arguments from `docs/01 §4`:
  hysteresis over single threshold, interlock priority, minimum dwell. Quantify: 18
  irrigation events in 21 days versus thousands of relay operations.
- 3.8 Failure-mode table — `docs/01 §5`.

---

## Chapter 4 · Hardware Implementation (6–8 pp)

Source: `docs/02_hardware_wiring.md`.

- 4.1 Component selection with justification, and a BOM table with costs.
- 4.2 **The substitution table** — Tinkercad has no DHT11 and no DHT library. State this as
  a platform constraint with the mitigation, and cite Autodesk's own substitution guidance.
  Handled well, this reads as awareness; handled badly, it looks like you did not know.
- 4.3 Circuit design — **Figure 4.1** Tinkercad screenshot, **Figure 4.2** schematic.
- 4.4 Pin map tables for both Uno and ESP32.
- 4.5 Sensor interfacing and calibration — TMP36 transfer function, LDR divider, HC-SR04
  time-of-flight with the temperature-dependence caveat, two-point soil calibration.
- 4.6 Actuator driving — relay, transistor, **flyback diode**, separate supply rail, common
  ground. Include why: the inductive kick otherwise injects a spike that looks exactly like
  your `spike` anomaly class.
- 4.7 Firmware — median-of-5 filter, control law, alert state machine, 20 s aggregation.
  Flowchart as **Figure 4.3**. Code in Appendix A, not inline.
- 4.8 Why two builds — the Tinkercad/Wokwi split, control logic identical.

---

## Chapter 5 · Cloud Integration (4–5 pp)

Source: `docs/03_thingspeak_setup.md`.

- 5.1 Platform selection with a comparison table (ThingSpeak / Blynk / Adafruit IO /
  InfluxDB+Grafana).
- 5.2 Channel configuration and field map.
- 5.3 Transmission protocol, HTTP return codes, retry behaviour.
- 5.4 **Rate limiting** — 15 s per channel, 960 messages per bulk call, unique timestamps.
  Explain that the 20 s publish interval is a design response, and that averaging ten
  samples also reduces ADC noise by √10.
- 5.5 Bulk historical upload — the round trip, with the downloaded feed as evidence.
- 5.6 Visualisations — six field charts plus three MATLAB visualisations, **Figures 5.1–5.9**.
- 5.7 React alerting.

---

## Chapter 6 · Dataset Generation and Preprocessing (8–10 pp)

Source: `docs/04 §§1–4`. This chapter is where a "sensor demo" becomes a project.

- 6.1 Rationale for simulation, stated honestly.
- 6.2 The physics model — every equation from `docs/04 §2`, with a constants table.
- 6.3 Sensor model — noise, ADC quantisation, DHT11 integer resolution.
- 6.4 Fault injection — the six classes, counts, durations, signatures. Emphasise
  `phantom_wet` and `tank_leak` as *contextual* anomalies where no single value is out of
  range.
- 6.5 Dataset schema — 30,240 rows, columns, units.
- 6.6 Preprocessing — validity gate (220 readings), grid check, gap-aware imputation,
  smoothing applied only to analytics.
- 6.7 Feature engineering — the seven groups, 96 columns, with the four fault-facing
  features given their own subsection.
- 6.8 **Validation of the simulator** — the water-balance coefficient recovery: analytics
  recovers +0.0980 %/min against a true 0.100 %/min. Put this in a box. It is independent
  evidence that the physics is self-consistent.

---

## Chapter 7 · Data Analytics (6–7 pp)

Source: `reports/analytics_tables.md`, `figures/01–07`.

- 7.1 Descriptive statistics — the full table with skew, kurtosis, CV.
- 7.2 Time-series behaviour — **Figure 01**, all six channels over 21 days.
- 7.3 Control-loop detail — **Figure 02**, the 3-day zoom. This single figure explains the
  hysteresis better than a page of text.
- 7.4 Correlation analysis — Pearson and Spearman, **Figure 03**. Interpret, do not just
  tabulate:
  - T ↔ RH = **−0.931** — thermodynamic, from the Magnus curve
  - T ↔ light = **+0.665** — radiative heating
  - soil ↔ T = **−0.362** — mediated by ET, weaker because irrigation resets it
  - Spearman > Pearson for soil (−0.406 vs −0.362) → the relationship is monotone but
    non-linear, which is a direct argument for tree models over linear regression
- 7.5 Diurnal and seasonal profiles — **Figure 04**, including irrigation activity by hour.
- 7.6 Distributions — **Figure 05**. Note light is strongly bimodal (CV 131 %) because half
  the day is dark; this is why `is_daytime` is an explicit feature.
- 7.7 Physical coupling — **Figure 06**, VPD vs drying rate.
- 7.8 Outlier screening — IQR, global z, rolling z. Report that the rolling-z detector
  achieves precision 0.268 / recall 0.088 against the injected faults, and state plainly
  that this is the bar the ML must clear.
- 7.9 Injected faults on the timeline — **Figure 07**.

---

## Chapter 8 · Machine Learning (12–14 pp) — the core chapter

Source: `docs/04 §§5–7`, `reports/model_metrics.md`, `figures/08–13`.

- 8.1 Problem formulation — three tasks, three learning paradigms.
- 8.2 **Label engineering** — all three candidate targets, and why two were rejected. Do not
  compress this; it is the most defensible part of the project.
- 8.3 **Validation protocol** — chronological split with the autocorrelation argument
  (lag-1 > 0.999), plus blocked TimeSeriesSplit.
- 8.4 M1 Random Forest Classifier — hyperparameters, classification report, confusion
  matrix, ROC and PR curves (**Figures 08**), baselines table, feature importance
  (**Figure 09**, Gini and permutation side by side).
- 8.5 M2 Random Forest Regressor — MAE/RMSE/R², actual-vs-predicted (**Figure 10**),
  parity plot and residual distribution (**Figure 11**), baselines, skill score,
  worst-case error discussion.
- 8.6 M3 Isolation Forest — feature-view ablation (0.62 → 0.88) and the centred-to-trailing
  deployability ablation (0.879 → 0.836), score separation, ROC,
  confusion matrix (**Figure 12**), detections timeline (**Figure 13**), recall by fault
  family, layered detection, event-level latency.
- 8.7 Comparative discussion — why Random Forest over SVM/XGBoost/LSTM here: tabular
  heterogeneous features, ~21 k training rows, native feature importance, no scaling
  requirement, OOB estimate for free, and it runs on a Raspberry Pi at the edge.
- 8.8 **Negative results and limitations** — the persistence failure on the pump-state
  target, drift detection latency, three missed fault events. A chapter that contains no
  negative results is a chapter nobody believes.

---

## Chapter 9 · Dashboard and Decision Fusion (4–5 pp)

- 9.1 Requirements — what an operator needs at a glance.
- 9.2 Layout — status pills, KPI strip, decision-support panel, telemetry grid, four tabs.
- 9.3 Fusion logic — how a model recommendation carrying an M3 flag becomes "verify the
  probe" rather than an actuation command.
- 9.4 Screenshots for all six scenarios, **Figures 9.1–9.6**.
- 9.5 Inference latency measurement.

---

## Chapter 10 · Testing (5–6 pp)

Source: `docs/05_test_cases.md`. All three suites: firmware (A1–A6), end-to-end ML
(S1–S6), methodology (C1–C9). Use the exact expected/actual tables — a test table with
real numbers in the "actual" column is far more convincing than a column of ticks.

---

## Chapter 11 · Results and Discussion (4–5 pp)

- 11.1 Consolidated results table.
- 11.2 Comparison with published work — position your MAE of 0.86 pp and RMSE of 1.94 pp
  against the 1–4 % VWC range in the literature, while noting your data are simulated and
  therefore cleaner.
- 11.3 Water-saving estimate — from the pump duty cycle (24.55 %) versus a fixed-schedule
  baseline. Be explicit that this is an estimate from simulation.
- 11.4 Limitations, restated compactly.

---

## Chapter 12 · Conclusion and Future Work (2–3 pp)

Future work worth naming (each one specific enough to be actionable):

1. Field validation on a real plot with a calibrated TDR reference probe.
2. LSTM/Temporal Fusion Transformer for multi-step forecasting, benchmarked against this
   Random Forest, not instead of it.
3. Online/streaming Isolation Forest with a trailing-window feature computation, removing
   the centred-window offline assumption.
4. Weather-forecast API integration — 6-hour rainfall probability would remove the largest
   remaining source of M2 error.
5. Zone-wise control with multiple nodes and a shared tank, turning this into a scheduling
   problem.
6. Edge deployment: quantise M1 and M2 to run on the ESP32 itself, removing the cloud from
   the decision path entirely.

---

## References

IEEE style, 25–35 entries. **Verify every DOI before submission.** Prefer FAO Irrigation and
Drainage Paper 56, the original Liu et al. Isolation Forest paper (ICDM 2008), Breiman's
Random Forests (2001), and recent IEEE Access / Computers and Electronics in Agriculture
papers for the applied work.

---

## Appendices

| | |
|---|---|
| A | Arduino firmware, both builds, syntax-highlighted |
| B | Python source: generator, preprocessing, training, dashboard |
| C | Full metrics JSON |
| D | Complete correlation matrices and descriptive statistics |
| E | Tinkercad circuit and ThingSpeak channel screenshots |
| F | Dataset schema, all 96 columns with units and definitions |

---

## A note on academic integrity

Your institution's AI-use policy applies. Everything in this repository is a working
artefact — the code runs, the numbers are real outputs. But the **prose of the report must
be written in your own voice**, from your own understanding of what the code does. The
fastest way to be certain you can defend it in the viva is to write each chapter after
re-running the corresponding script and reading its output yourself.
