# 08 · Viva Questions and Answers

62 questions. The ones marked **★** are the ones most likely to expose a shallow project —
learn those first. Answers are written the way you should say them: a direct claim, then
the number or reason that supports it.

---

## A · Hardware and firmware

**A1. Why hysteresis instead of a single soil-moisture threshold?**
With one threshold at 35 %, sensor noise of about ±0.5 pp around the boundary toggles the
relay every sample. The 35–60 % dead band gave 18 irrigation events across 21 days; a single
set-point would produce thousands of relay operations, well past the ~100,000-cycle
mechanical life of an SRD-05VDC relay. It also matches irrigation practice — you refill the
root zone to field capacity, you do not hold it at a line.

**A2. What does the minimum dwell time do?**
It blocks a state change within 10 s of the previous one. It covers the case where the
filtered reading sits exactly on a set-point and oscillates by one ADC count. Hysteresis
handles slow crossings; dwell time handles fast ones.

**★A3. Why is the low-water check evaluated before the irrigation logic?**
Because it is an interlock, not a condition. Running a centrifugal pump dry destroys the
seal in minutes. Interlocks belong above the control logic so no combination of inputs can
bypass them. In the code it is the first branch, and every other branch is `elif`.

**A4. What happens when the ultrasonic sensor returns no echo?**
`pulseIn` times out at 30 ms and returns 0, which the code maps to −1. That is treated as
low water, so the pump is inhibited and alert code 4 is raised. The system fails **closed**.
A missed irrigation cycle costs a day of growth; a dry-run pump costs the pump.

**A5. Why a median-of-5 filter rather than a moving average?**
A median is robust to outliers; a mean is not. A single 5σ spike from cable EMI shifts a
5-point mean by one fifth of the spike but leaves the median untouched. It is also cheap —
an insertion sort on five integers, no floating point.

**★A6. Tinkercad has no DHT11. How did you handle that?**
Tinkercad Circuits ships no DHT11 model and no DHT library. Following Autodesk's published
substitution guidance, temperature uses a TMP36 and humidity a potentiometer, since both are
three-pin analogue parts. The control law, alert state machine, filtering and telemetry frame
are identical between that build and the ESP32 build; only the four acquisition functions
differ. I documented the mapping in a substitution table rather than hiding it.

**A7. Why does the connected build use ESP32 rather than ESP8266?**
The ESP8266 exposes exactly one ADC pin. This design needs two simultaneous analogue
channels, so an ESP8266 build would require a CD4051 multiplexer or an ADS1115 I²C ADC. The
ESP32 has 15 usable ADC channels. There is a further constraint: only ADC1, GPIO 32–39, is
usable while WiFi is active, because ADC2 is claimed by the radio — which is why both
analogue sensors sit on GPIO 34 and 35.

**A8. Why is there a diode across the motor?**
It is a flyback diode. When the relay opens, the motor's inductance drives the voltage
sharply negative and the resulting spike propagates into the supply. Beyond damaging the
switching element, it corrupts ADC readings — which then look exactly like the `spike`
anomaly class I trained the detector on. Suppressing it at source is better than detecting
it downstream.

**A9. Why must the motor have a separate supply?**
Stall current on even a small DC motor exceeds the Arduino regulator's limit and browns out
the MCU mid-decision. The supplies share only ground, so the relay input sees a defined
level.

**A10. How is the TMP36 reading converted?**
`Vout = 0.5 + 0.01·T`, so `T = (analogRead × 5/1023 − 0.5) × 100`. Reversing supply and
ground destroys a real TMP36.

**A11. How do you convert ultrasonic time-of-flight to tank level?**
`distance = pulse_µs × 0.0343 / 2`, then
`level% = (1 − (distance − 4)/40) × 100` for a 40 cm column with the sensor 4 cm above the
full line. The 0.0343 cm/µs is the speed of sound at 20 °C and varies about 0.6 % per 10 °C,
so across a 15–40 °C day the level drifts around 0.3 pp. I have not compensated for it and
it is listed as a known error source.

**A12. Why average ten samples before publishing?**
Two reasons. ThingSpeak's free tier accepts one update per 15 s, so the 20 s publish
interval is required. And averaging ten samples reduces ADC noise by √10, so the constraint
also improved the data.

**A13. What are the alert codes?**
0 normal, 1 low water, 2 high temperature, 3 both, 4 sensor fault — with distinct buzzer
tones so the fault is identifiable without looking at the LCD.

---

## B · Cloud and networking

**★B1. Can Tinkercad send data to ThingSpeak?**
No. Tinkercad Circuits has no network stack — no WiFi board, no HTTP, no internet. That is
precisely why there are two builds. The cloud path is demonstrated in Wokwi, which simulates
the full 802.11 stack through DNS and HTTP and routes it to the real internet through an IoT
gateway. I can show a Wireshark capture of the HTTP POST to `api.thingspeak.com`.

**B2. What is the ThingSpeak rate limit and how did you design around it?**
One update per channel every 15 seconds on a free account; the server drops anything faster
and returns 0. The node publishes every 20 s. For the 21-day history I used the bulk-update
endpoint, which allows 960 messages per call with calls at least 15 s apart, and requires
unique timestamps — duplicates cause the entire call to be rejected.

**B3. How many messages was the historical upload?**
The full campaign at 1-minute resolution is 30,240 messages, 32 bulk calls, about 8 minutes.
The default is a 5-minute resample — 6,048 messages in 7 calls — which is plenty for
readable plots and conserves the annual free allowance.

**B4. Why six fields and not eight?**
A ThingSpeak channel has eight fields; the design uses six for the six physical channels and
puts the human-readable alert in the status string, which keeps two fields free for future
sensors such as pH or EC.

**B5. What if ThingSpeak is unavailable?**
The analytics layer reads a CSV, so the broker is decoupled. Swapping to Blynk, Adafruit IO
or a local InfluxDB+Grafana stack only changes `thingspeak_io.py`. More importantly, the
control loop never depended on the cloud in the first place.

**B6. What does an HTTP return of 0 mean?**
Either you are posting faster than the rate limit, or the payload is malformed. 401 is a bad
write key, −301 a failed connection, −304 a timeout.

---

## C · Data and simulation

**★C1. Your data are simulated. Why should I believe any of the results?**
Two arguments. First, the structure is not imposed — soil moisture is integrated from a
water balance, evapotranspiration is driven by vapour-pressure deficit and irradiance, and
humidity is derived from specific humidity through the Magnus curve. Every correlation in
the dataset is a consequence of stated equations rather than something I set. Second, the
analytics layer independently recovers a physical parameter it was never given: a
least-squares fit on the first week alone returns a pump recharge coefficient of
+0.0980 %/min against the simulator's true 0.100 %/min. The pipeline is self-consistent.
The limitation is real, though, and field validation is the first item of future work.

**C2. Why is temperature–humidity correlation as strong as −0.93?**
Because it is thermodynamic. I generated specific humidity as a slowly varying process and
derived relative humidity through the Magnus–Tetens saturation curve. Warm air holds more
vapour, so RH falls as T rises even with constant water content. I did not choose −0.93; it
fell out.

**C3. Why is Spearman correlation stronger than Pearson for soil moisture?**
−0.406 versus −0.362. That gap says the relationship is monotone but non-linear, which is a
direct argument for tree-based models over linear regression — and the logistic regression
baseline underperforming the forest by 19 F1 points is the empirical confirmation.

**C4. What is vapour-pressure deficit and why is it a feature?**
VPD is `e_s(T) × (1 − RH/100)` — the difference between how much moisture air could hold and
how much it does. It is the actual thermodynamic driver of evaporation. Temperature and
humidity separately are proxies; VPD is the mechanism, so encoding it directly gives the
model the physics instead of making it rediscover the interaction.

**C5. What is Ks in your ET model?**
The FAO-56 soil-water stress coefficient. A dry soil transpires less because the plant
closes its stomata. Without it, soil would dry linearly to zero, which is physically wrong
and would have made the regression task artificially easy.

**C6. Why 1-minute sampling and 21 days?**
One minute gives a 30-step horizon for the 30-minute forecast, which is enough for lag and
rolling features. Twenty-one days gives 18 full irrigation cycles, two engineered heatwaves,
six rain events and a low-water episode — enough for a 15/6-day chronological split with
every scenario present in both halves.

**★C7. How did you create the low-water scenario?**
By suppressing the scheduled tank top-up on days 11 to 14. The tank bottoms out at 18.1 %,
the interlock fires for 2,137 minutes, and soil moisture falls to 15.8 % because irrigation
is blocked. It is a designed stress episode, not an accident, and it is what test scenario
S4 draws on.

**C8. What are the six fault classes?**
Spike (2.5–5.5σ transient), dropout (−999 sentinel), stuck (latched reading), drift (linear
ramp), phantom-wet (soil rises with the pump off and no rain), and tank leak (level falls
with the pump off). 1,688 anomalous samples, 5.58 % of the campaign.

**★C9. What is a contextual anomaly and which of yours are contextual?**
A contextual anomaly is one where every individual value is inside its normal range and only
the joint behaviour is impossible. Phantom-wet and tank-leak are the clear cases: 71 % soil
moisture is a perfectly valid reading, but not when the pump is off, no rain has fallen, and
the water balance forbids that rate of increase. These are the reason a univariate threshold
detector is insufficient and the reason my feature set includes water-balance residuals.

**C10. Why did you keep both a raw and a processed dataset?**
The raw file is what the node transmits — noisy, quantised, with faults and −999 dropouts
intact. The processed file is post-cleaning and post-feature-engineering. Keeping them
separate means the cleaning stage is auditable and the anomaly detector can be evaluated
against faults that the cleaning stage did not silently repair.

**C11. You smoothed the data. Doesn't that destroy the anomalies?**
It would, which is why smoothing is applied only to columns suffixed `_smooth`, used for
analytics plots. The ML pipeline sees the unsmoothed signal. Median-filtering before anomaly
detection would remove exactly the spikes you are trying to detect.

**C12. How do you handle missing data?**
A validity gate first — sentinel values and out-of-range readings become NaN, 220 of them.
Then gap-aware imputation: time interpolation for gaps up to 15 minutes, because the physics
is smooth at 1-minute scale, and forward-fill with an explicit flag beyond that. The flag
matters — the model can learn that imputed regions are less trustworthy.

---

## D · Machine learning

**★D1. What exactly does your classifier predict?**
Whether root-zone moisture will cross the 35 % management-allowed-depletion line within the
next 120 minutes under a no-irrigation continuation, given that water is available. It is
forward-looking, agronomically meaningful, and — importantly — the feature set excludes
every pump-state variable, so the model must infer demand from micro-climate and soil
dynamics rather than reading it off the actuator.

**★D2. Isn't your label just a restatement of the control rule?**
That is exactly the trap I tested for, and I report it as a control. Training on the literal
rule label gives accuracy 0.9974 — the forest memorises an `if` statement and learns
nothing. That is why I built a forward-looking target instead. Against the reactive
threshold rule as a baseline, my adopted model gets F1 0.881 versus 0.052.

**★D3. Did you compare against a trivial baseline?**
Yes, and one of them beat me. On an earlier target — pump state 30 minutes ahead — the
Random Forest got F1 0.906 and a persistence baseline got 0.921. The baseline won, because
with pump status in the features the target was close to a lagged copy of an input and
97 % of minutes are steady-state. I report that as a negative result and retargeted the
model. The one place the forest did add value was the transition region within ±45 minutes
of a real switch: F1 0.847 versus persistence 0.670 — which shows aggregate metrics were
hiding where the difficulty actually lives.

**★D4. Why chronological split rather than `train_test_split`?**
Because consecutive minutes are near-duplicates — lag-1 autocorrelation of soil moisture
exceeds 0.999. A random split puts minute *t* in train and minute *t+1* in test, so the
model is scored on rows it has effectively memorised. Accuracy would inflate towards 1.0 and
mean nothing. Train is days 0–14, test is days 15–20, and the test period is strictly in the
future.

**D5. Your TimeSeriesSplit F1 is 0.770 ± 0.305. Isn't that variance alarming?**
It is informative rather than alarming. The early folds contain very few positive samples
because the campaign is non-stationary — the low-water episode and the heatwaves are not
uniformly distributed. The standard deviation is measuring non-stationarity across the
campaign, not model instability, and that is why I quote the held-out chronological result
as the headline and the CV as a robustness check.

**D6. Why Random Forest rather than XGBoost, SVM, or an LSTM?**
Tabular heterogeneous features with about 21,000 training rows. Random Forest needs no
feature scaling, gives native importance and an out-of-bag estimate for free, is hard to
overfit with sensible leaf sizes, and runs on a Raspberry Pi at the edge. XGBoost would
likely gain a point or two at the cost of more tuning. An LSTM needs far more data to beat
explicit lag features on a 30-minute horizon, and I would rather report a strong simple
model with honest baselines than a weak complex one.

**D7. What does out-of-bag score mean and what did you get?**
Each tree trains on a bootstrap sample of about 63 % of rows; the remaining 37 % are its
out-of-bag set. Averaging predictions over the trees that did not see each row gives a
free validation estimate. M1's OOB is 0.9968 against a held-out accuracy of 0.9782 — the gap
is expected, because OOB rows are temporally interleaved with training rows and so benefit
from the same autocorrelation that makes random splits unsafe.

**★D8. Gini importance versus permutation importance — why report both?**
Gini importance measures how much each feature reduced impurity during training. It is
biased towards high-cardinality continuous features and is computed on training data.
Permutation importance shuffles a feature in the **test** set and measures the drop in
performance, so it reflects genuine predictive contribution on unseen data. They disagree
when features are correlated, and the disagreement is itself diagnostic.

**D9. Your top features are dominated by soil moisture. Isn't that circular?**
For a 30-minute forecast it is physically correct — the strongest predictor of soil moisture
in half an hour is soil moisture now. The interesting result is what comes next:
`deficit_from_target` at 0.359, `soil_ma_30` at 0.117 and the lag structure. The model has
learned that the *rate* and *recent trajectory* carry information beyond the level, which is
the water balance expressed in features.

**D10. Explain your regression metrics.**
MAE 0.858 pp is the average absolute error — the intuitive one. RMSE 1.942 pp squares errors
before averaging, so it penalises large misses; the gap between them tells you errors are
not uniform. R² 0.948 is the fraction of variance explained. Against persistence at RMSE
3.226, the skill score is 0.638 — the model removes 64 % of the baseline's error variance.

**D11. What is your worst-case error and where does it occur?**
14.1 pp, at pump-start transients. The moment irrigation begins, the derivative of soil
moisture flips sign abruptly, and a tree ensemble trained mostly on smooth drying periods
under-reacts. It is a known and explainable failure mode, and the fix would be an explicit
pump-transition feature or a separate model for the first minutes of a cycle.

**D12. How does Isolation Forest work?**
It builds random trees by picking a random feature and a random split point. Anomalies sit in
sparse regions, so they get isolated in fewer splits. The score is the average path length
across the ensemble, normalised. It is unsupervised, linear in the number of samples, and
does not need a distance metric — which matters here because I have 16 features on
incompatible scales.

**★D13. Your anomaly F1 is only 0.45. Isn't that poor?**
It depends on what you count. Sample-level F1 is 0.383 with ROC-AUC 0.836, and both are true.
But at **event level**, which is what an operator experiences, 11 of 14 fault events in the
test period were detected with a median latency of 3 minutes. Sample-level recall penalises
the model for the first 20 minutes of a slow drift that it does eventually catch. The right
comparison is the baseline: a rolling z-score detector gets precision 0.268 and recall 0.088.
Isolation Forest is about 1.2× the precision at 5× the recall.

**★D14. Why is dropout recall exactly zero?**
By design. A −999 sentinel is caught deterministically by the range check in firmware and
preprocessing, at precision 1.000. Crediting machine learning with catching a −999 would be
dishonest. I report a two-layer stack: Layer 1 handles validity, Layer 2 handles contextual
faults, and the combined figures are precision 0.353, recall 0.521.

**★D15. What was the biggest thing you changed after seeing results?**
The Isolation Forest feature view. Fed raw sensor levels it got ROC-AUC 0.62 — because
Isolation Forest scores low-density regions and the normal diurnal envelope, midday peaks
and midnight troughs, *is itself* a large legitimate sparse tail. It spent its budget
flagging normal afternoons. Replacing levels with residuals — flat-run length, deviation
from the six-hour envelope, monotonicity, water-balance residual — lifted it to 0.88. The
lesson is that for density-based detectors you should feed "how far is this from what the
physics allows", not "what is the value".

**D16. What does `flat_run` do and why is it necessary?**
It counts consecutive minutes with zero change. A latched sensor is perfectly normal in
level and often normal in 60-minute standard deviation too, because most fault windows are
shorter than the window. Its run length is the only impossible thing about it. Adding it
took stuck-sensor recall from 0 to 0.708.

**D17. Why `q_dev_360` instead of a humidity deviation?**
Relative humidity swings 40 points a day purely because temperature moves, so a drifting RH
sensor is invisible against that background. Specific humidity is conserved under
temperature change, so a drift shows up as a `q` excursion. It is the same trick as looking
at potential temperature instead of temperature in meteorology.

**D18. What is `contamination` and how did you set it?**
It is the assumed proportion of anomalies, which sets the decision threshold on the score. I
set it to 0.05, close to the observed 5.58 % fault rate. I also report a threshold sweep —
the F1-optimal operating point flags the top 8 % and gives F1 0.467 — so the choice is
documented rather than assumed.

**D19. Why `class_weight='balanced_subsample'`?**
The positive class is 15.4 % of samples. Without reweighting, the forest maximises accuracy
by under-predicting the minority class, and recall on the class you actually care about
collapses. `balanced_subsample` reweights within each tree's bootstrap sample rather than
globally, which suits bagging.

**D20. Why is precision higher than recall in M1?**
0.922 versus 0.843. The model is conservative — it misses 129 genuine demand events but
raises only 59 false alarms. For irrigation that is arguably the wrong trade-off, since a
missed cycle costs growth and a false alarm costs a little water. Lowering the decision
threshold from 0.5 would trade precision for recall, and the precision-recall curve in
Figure 08 shows exactly what that costs.

**D21. Are your features causally valid?**
Every feature is computable at time *t* from data at or before *t*; only targets look
forward. The one caveat I state explicitly is that `_dev_360` uses a centred window, which
is legitimate for offline fault forensics but would need to become a trailing window in a
live deployment, with a corresponding detection delay.

---

## E · System and design

**E1. Why three models rather than one?**
They answer different questions and fail differently. M1 is the decision layer and gives a
calibrated probability, so marginal calls can be escalated. M2 is the planning layer and
gives a magnitude that a classifier discards. M3 is the trust layer — M1 and M2 both assume
their inputs are real, and M3 is the only component that questions them. It has to be
unsupervised because you cannot label field faults you have not encountered yet.

**★E2. Show me why the trust layer matters, concretely.**
Test scenario S6. A calibration drift inflates the soil probe to 71 %. M2's error jumps to
7.2 pp, roughly eight times its normal MAE of 0.86 — and it degrades silently, producing a
confident wrong number. M3 flags the reading, and the dashboard shows "verify the probe"
instead of an actuation command. Without M3 the system would have irrigated on corrupt data.

**E3. In scenario S4 the soil is dry but the model says no irrigation. Explain.**
Soil is at 35.7 %, which is below the set-point, but the tank is at 17.8 %, below the 20 %
interlock. `agronomic_demand` is defined as demand conditional on water being available, and
the model returns probability 0.064. It learned the interlock from `water_level_pct` and
`water_available` — I did not encode the rule into the model.

**E4. Why doesn't high temperature trigger irrigation?**
Because irrigating on air temperature rather than soil water is exactly the over-watering
behaviour the project is meant to prevent. In S5, temperature is 36 °C but soil is at 44.5 %
and will fall only about 1.2 pp in the next half hour. Heat raises an advisory alert;
soil-water state drives actuation.

**E5. What is your inference latency?**
Under 50 ms per reading for all three models on a laptop CPU. The models are ~400 trees with
depth ≤ 22, so they would run comfortably on a Raspberry Pi at the edge. Moving inference
onto the node is listed as future work and would remove the cloud from the decision path.

**E6. How would you deploy this for real?**
Field-calibrate the soil probe with a two-point wet/dry procedure against a TDR reference,
use a capacitive probe rather than resistive to avoid electrolytic corrosion, run the node
on solar with a LiPo and deep sleep between samples, move to LoRaWAN if the field is beyond
WiFi range, and retrain seasonally because the crop coefficient changes through the growth
stages.

**E7. What is the water saving?**
Pump duty cycle in the simulation is 24.55 %, and the predictive layer allows irrigation to
be scheduled before stress rather than after. I would rather not quote a headline percentage
saving, because it would be a saving measured against a baseline I also simulated. The
defensible claim is the recall gap: 0.843 versus 0.027 for the reactive rule.

**E8. What would you do differently with another month?**
Field validation first — the simulation is the project's main limitation, and even a
two-week deployment with a reference probe would change what I can claim. Second, integrate
a weather-forecast API; unforecast rainfall is the largest remaining source of M2 error.
Third, move the detector to a trailing-window formulation so it is deployable online.

---

## F · Questions you should be ready for but hope not to get

**F1. Run the pipeline for me right now.**
Have a terminal open with the virtual environment already active. `01` takes ~20 s, `02`
~40 s, `03` ~4 minutes. If you have to run something live, run `02` — it is fast and prints
the correlation table and the coefficient-recovery line, which are your best evidence.

**F2. Show me where in the code that happens.**
Know these five locations cold: the control law in the firmware; the ET function in
`01_generate_dataset.py`; the label definition block in the same file; the feature groups at
the top of `03_train_models.py`; the `IF_FEATURES` list with its ablation comment.

**F3. What is the single weakest part of this project?**
That the data are simulated. I will not defend it beyond the two arguments in C1 — that the
structure emerges from stated physics, and that the analytics independently recover a
simulator constant to within 2 %. Field validation is the first item of future work, and it
is first for exactly this reason.

**F4. How much of this did you write yourself?**
Answer honestly and specifically, in line with your institution's AI-use policy. The
defensible position is that you understand and can modify every component — which is only
true if you have actually read the code and re-run it. Spend an afternoon changing
parameters and watching what breaks; that is what makes this answer easy.
