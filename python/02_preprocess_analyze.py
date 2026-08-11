r"""
02_preprocess_analyze.py
========================
Stage 2 of the pipeline: turn the raw telemetry stream into a modelling-ready
feature table, and produce the descriptive / correlation / trend / outlier
analytics required by the report.

Inputs :  data/sensor_data_raw.csv
Outputs:  data/processed_dataset.csv
          data/analytics_summary.json
          figures/*.png
          reports/analytics_tables.md

Run:  python 02_preprocess_analyze.py
"""

import os
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "figure.dpi": 120, "savefig.dpi": 150, "font.size": 9,
    "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False,
    "axes.spines.right": False, "figure.autolayout": True,
})

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")
FIG = os.path.join(ROOT, "figures")
REP = os.path.join(ROOT, "reports")
for d in (FIG, REP):
    os.makedirs(d, exist_ok=True)

SENSORS = ["temperature_c", "humidity_pct", "soil_moisture_pct",
           "light_pct", "water_level_pct"]

# Physically admissible ranges - anything outside is a hard sensor fault
VALID = {
    "temperature_c":     (-5.0, 60.0),
    "humidity_pct":      (0.0, 100.0),
    "soil_moisture_pct": (0.0, 100.0),
    "light_pct":         (0.0, 100.0),
    "water_level_pct":   (0.0, 100.0),
}

log = []


def note(msg):
    print(msg)
    log.append(msg)


# ==========================================================================
# 1. LOAD
# ==========================================================================
df = pd.read_csv(os.path.join(DATA, "sensor_data_raw.csv"), parse_dates=["timestamp"])
note(f"[load] raw shape = {df.shape}")
df = df.sort_values("timestamp").reset_index(drop=True)

# ==========================================================================
# 2. CLEANING
# ==========================================================================
# 2a. Sentinel dropouts (-999) and out-of-range values -> NaN
n_bad_before = 0
for c in SENSORS:
    lo, hi = VALID[c]
    bad = (df[c] <= -900) | (df[c] < lo) | (df[c] > hi)
    n_bad_before += int(bad.sum())
    df.loc[bad, c] = np.nan
    df[f"{c}_was_missing"] = bad.astype(int)
note(f"[clean] invalid / dropout readings converted to NaN : {n_bad_before}")

# 2b. Regular 1-minute grid check (a real node drops packets)
full_index = pd.date_range(df.timestamp.min(), df.timestamp.max(), freq="1min")
missing_ts = full_index.difference(df.timestamp)
note(f"[clean] missing timestamps on the 1-min grid       : {len(missing_ts)}")

# 2c. Gap-aware imputation.
#     Short gaps (<= 15 min) -> time interpolation (physics is smooth at 1 min).
#     Long gaps               -> forward fill + explicit flag, never invented.
MAX_INTERP = 15
df = df.set_index("timestamp")
for c in SENSORS:
    s = df[c]
    grp = s.notna().cumsum()
    gap_len = s.isna().groupby(grp).transform("sum")
    short = s.isna() & (gap_len <= MAX_INTERP)
    df[c] = s.interpolate(method="time", limit=MAX_INTERP, limit_area="inside")
    df[c] = df[c].ffill().bfill()
    df[f"{c}_imputed_long"] = (s.isna() & ~short).astype(int)
df = df.reset_index()
note(f"[clean] residual NaNs after imputation             : {int(df[SENSORS].isna().sum().sum())}")

# 2d. Light despiking for the physically slow channels only (median filter,
#     window 5). NOTE: this is applied to a *copy* used for analytics/plots;
#     the ML feature table keeps the unfiltered signal so that the Isolation
#     Forest still sees genuine faults.
smooth = df[SENSORS].rolling(5, center=True, min_periods=1).median()
smooth.columns = [c + "_smooth" for c in SENSORS]
df = pd.concat([df, smooth], axis=1)


# ==========================================================================
# 3. FEATURE ENGINEERING
# ==========================================================================
t = df["timestamp"]
df["hour"] = t.dt.hour + t.dt.minute / 60.0
df["minute_of_day"] = t.dt.hour * 60 + t.dt.minute
df["day_of_campaign"] = (t - t.iloc[0]).dt.total_seconds() // 86400
df["hour_sin"] = np.sin(2 * np.pi * df.minute_of_day / 1440)
df["hour_cos"] = np.cos(2 * np.pi * df.minute_of_day / 1440)
df["is_daytime"] = ((df.hour >= 6.2) & (df.hour <= 18.6)).astype(int)

# --- lags: the model may only look backwards in time ----------------------
for lag in (5, 15, 30, 60):
    df[f"soil_lag_{lag}"] = df["soil_moisture_pct"].shift(lag)
    df[f"temp_lag_{lag}"] = df["temperature_c"].shift(lag)
for lag in (15, 30):
    df[f"hum_lag_{lag}"] = df["humidity_pct"].shift(lag)
    df[f"light_lag_{lag}"] = df["light_pct"].shift(lag)
df["pump_lag_1"] = df["pump_status"].shift(1)
df["pump_lag_15"] = df["pump_status"].shift(15)
df["pump_on_last_60"] = df["pump_status"].rolling(60, min_periods=1).sum()

# --- rates of change (drying velocity is the physically meaningful signal) --
df["soil_rate_15"] = (df["soil_moisture_pct"] - df["soil_lag_15"]) / 15.0
df["soil_rate_60"] = (df["soil_moisture_pct"] - df["soil_lag_60"]) / 60.0
df["temp_rate_15"] = (df["temperature_c"] - df["temp_lag_15"]) / 15.0
df["water_rate_30"] = (df["water_level_pct"] - df["water_level_pct"].shift(30)) / 30.0

# --- rolling context ------------------------------------------------------
for w in (30, 120):
    df[f"soil_ma_{w}"] = df["soil_moisture_pct"].rolling(w, min_periods=1).mean()
    df[f"temp_ma_{w}"] = df["temperature_c"].rolling(w, min_periods=1).mean()
    df[f"light_ma_{w}"] = df["light_pct"].rolling(w, min_periods=1).mean()
df["temp_std_60"] = df["temperature_c"].rolling(60, min_periods=2).std()
df["soil_std_60"] = df["soil_moisture_pct"].rolling(60, min_periods=2).std()

# --- dispersion + contextual deviation for EVERY channel -------------------
# A latched ("stuck") sensor is perfectly normal in level but impossible in
# variance; a drifting sensor is normal instantaneously but departs from its own
# 6-hour envelope. These two views make both failure modes separable.
for c in SENSORS:
    df[f"{c}_std_60"] = df[c].rolling(60, min_periods=5).std()
    # TRAILING window, deliberately not centred. A centred window needs future
    # samples, so a detector trained on it cannot be deployed online. Using the
    # trailing form here means the live node computes bit-identical features.
    df[f"{c}_dev_360"] = df[c] - df[c].rolling(361, min_periods=60).median()
    # flat-run length: how many consecutive minutes the reading has not moved.
    # This is the classic latched-sensor signature and is invisible to std/dev.
    _same = (df[c].diff().abs() < 1e-9)
    _grp = (~_same).cumsum()
    df[f"{c}_flat_run"] = _same.groupby(_grp).cumsum().clip(upper=180)
    # monotonicity of the last hour: +1 = rising every minute, -1 = falling.
    # A calibration drift is a sustained one-way ramp; real weather is not.
    df[f"{c}_mono60"] = np.sign(df[c].diff()).rolling(60, min_periods=10).mean()

# --- water-balance bookkeeping over the last 30 minutes --------------------
df["pump_minutes_30"] = df["pump_status"].rolling(30, min_periods=1).sum()
df["soil_delta_30"] = df["soil_moisture_pct"] - df["soil_moisture_pct"].shift(30)
df["water_delta_30"] = df["water_level_pct"] - df["water_level_pct"].shift(30)

# --- specific humidity: the conserved quantity behind T/RH -----------------
# RH swings 40 points a day purely because T moves; q does not. A drifting RH
# sensor therefore shows up as a q excursion, not an RH excursion.
_es = 6.112 * np.exp(17.67 * df.temperature_c / (df.temperature_c + 243.5))
_e = _es * df.humidity_pct / 100.0
df["q_est"] = 0.622 * _e / (1000.0 - _e)
df["q_dev_360"] = df["q_est"] - df["q_est"].rolling(361, min_periods=60).median()

# --- physically derived features ------------------------------------------
es = 6.112 * np.exp(17.67 * df.temperature_c / (df.temperature_c + 243.5))
df["vpd_hpa"] = es * (1 - df.humidity_pct / 100.0)          # atmospheric demand
df["heat_index_proxy"] = df.temperature_c * (1 + 0.01 * (100 - df.humidity_pct))
df["et_proxy"] = df.vpd_hpa * (0.25 + 0.75 * df.light_pct / 100.0)
df["water_available"] = (df.water_level_pct > 20).astype(int)
df["deficit_from_target"] = 60.0 - df.soil_moisture_pct     # to upper set-point

# Residual between the measured 30-min soil-moisture change and what the water
# balance permits. Coefficients are least-squares calibrated on the first week
# only (see report S6.4); they are NOT taken from the simulator.
_cal = df.iloc[:7 * 1440]
_A = np.c_[_cal.pump_minutes_30.fillna(0), _cal.et_proxy.fillna(0), np.ones(len(_cal))]
_b = _cal.soil_delta_30.fillna(0)
_coef, *_ = np.linalg.lstsq(_A, _b, rcond=None)
note(f"[feature] water-balance calibration: d(soil)/30min = "
     f"{_coef[0]:+.4f}*pump_min {_coef[1]:+.5f}*ET_proxy {_coef[2]:+.4f}")
df["soil_delta_expected_30"] = (_coef[0] * df.pump_minutes_30
                                + _coef[1] * df.et_proxy + _coef[2])
df["hydro_residual"] = df["soil_delta_30"] - df["soil_delta_expected_30"]

# Tank must only fall while the pump runs. A fall with the pump off is a leak.
df["tank_residual"] = df["water_delta_30"] + 0.047 * df["pump_minutes_30"]

df = df.dropna(subset=[c for c in df.columns
                       if c.startswith(("soil_lag", "temp_lag", "hum_lag", "light_lag"))
                       or c in ("soil_delta_30", "water_delta_30", "hydro_residual")])
df = df.copy()
df = df.reset_index(drop=True)
note(f"[feature] engineered table shape = {df.shape}")


# ==========================================================================
# 4. DESCRIPTIVE STATISTICS
# ==========================================================================
desc = df[SENSORS].describe(percentiles=[.05, .25, .5, .75, .95]).T
desc["skew"] = df[SENSORS].skew()
desc["kurtosis"] = df[SENSORS].kurtosis()
desc["cv_%"] = 100 * desc["std"] / desc["mean"]
desc = desc.round(3)
print("\n--- DESCRIPTIVE STATISTICS ---")
print(desc.to_string())

# ==========================================================================
# 5. CORRELATION ANALYSIS
# ==========================================================================
CORR_COLS = SENSORS + ["vpd_hpa", "et_proxy", "pump_status",
                       "soil_rate_60", "soil_moisture_future_30"]
pearson = df[CORR_COLS].corr(method="pearson")
spearman = df[CORR_COLS].corr(method="spearman")
print("\n--- PEARSON CORRELATION (sensors) ---")
print(pearson.loc[SENSORS, SENSORS].round(3).to_string())

# lagged cross-correlation: how long does temperature lead soil drying?
# evaluated only while the pump is OFF, otherwise irrigation recharge masks ET
dry = df[df.pump_status == 0]
lags = np.arange(0, 361, 10)
xcorr = [dry["temperature_c"].corr(dry["soil_rate_60"].shift(-int(L))) for L in lags]
best_lag = int(lags[int(np.nanargmin(xcorr))])
note(f"[corr] temperature leads maximum soil drying rate by ~{best_lag} min "
     f"(r = {np.nanmin(xcorr):.3f})")

# ==========================================================================
# 6. OUTLIER / ANOMALY ANALYSIS (statistical baselines)
# ==========================================================================
outlier_tbl = []
df["outlier_votes"] = 0
for c in SENSORS:
    q1, q3 = df[c].quantile([.25, .75])
    iqr = q3 - q1
    iqr_out = (df[c] < q1 - 1.5 * iqr) | (df[c] > q3 + 1.5 * iqr)

    z = (df[c] - df[c].mean()) / df[c].std()
    z_out = z.abs() > 3

    # rolling / contextual z-score - catches faults hidden inside the diurnal cycle
    mu = df[c].rolling(241, center=True, min_periods=30).median()
    sd = df[c].rolling(241, center=True, min_periods=30).std().replace(0, np.nan)
    roll_out = ((df[c] - mu) / sd).abs() > 3.0

    df["outlier_votes"] += roll_out.fillna(False).astype(int)
    outlier_tbl.append({
        "sensor": c,
        "iqr_outliers": int(iqr_out.sum()),
        "global_z_outliers": int(z_out.sum()),
        "rolling_z_outliers": int(roll_out.sum()),
        "pct_rolling": round(100 * roll_out.mean(), 3),
    })
outlier_tbl = pd.DataFrame(outlier_tbl)
print("\n--- OUTLIER SCREENING ---")
print(outlier_tbl.to_string(index=False))

# how well does a plain statistical rule recover the injected faults?
tp = int(((df.outlier_votes > 0) & (df.is_anomaly == 1)).sum())
fp = int(((df.outlier_votes > 0) & (df.is_anomaly == 0)).sum())
fn = int(((df.outlier_votes == 0) & (df.is_anomaly == 1)).sum())
prec = tp / max(tp + fp, 1)
rec = tp / max(tp + fn, 1)
note(f"[baseline] rolling-z detector vs injected faults: "
     f"precision={prec:.3f} recall={rec:.3f} (this is the bar Isolation Forest must beat)")

# ==========================================================================
# 7. TREND / SEASONALITY
# ==========================================================================
diurnal = df.groupby(df.minute_of_day // 30 * 30)[SENSORS].mean()
daily = df.groupby("day_of_campaign")[SENSORS + ["pump_status"]].mean()
pump_by_hour = df.groupby(df.hour.astype(int))["pump_status"].mean() * 100


# ==========================================================================
# 8. FIGURES
# ==========================================================================
def save(fig, name):
    p = os.path.join(FIG, name)
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    print(f"  figure -> {name}")


print("\n--- FIGURES ---")

# 8.1 full multi-channel time series (the "ThingSpeak wall")
fig, ax = plt.subplots(6, 1, figsize=(12, 13), sharex=True)
series = [("temperature_c", "Temperature (C)", "#c0392b"),
          ("humidity_pct", "Humidity (%)", "#2980b9"),
          ("soil_moisture_pct", "Soil moisture (%)", "#8e6e3c"),
          ("light_pct", "Light intensity (%)", "#f39c12"),
          ("water_level_pct", "Tank level (%)", "#16a085")]
for a, (c, lab, col) in zip(ax, series):
    a.plot(df.timestamp, df[c], lw=0.5, color=col)
    a.set_ylabel(lab, fontsize=8)
ax[2].axhline(35, ls="--", c="r", lw=0.8)
ax[2].axhline(60, ls="--", c="g", lw=0.8)
ax[4].axhline(20, ls="--", c="r", lw=0.8)
ax[0].axhline(35, ls="--", c="k", lw=0.8)
ax[5].fill_between(df.timestamp, 0, df.pump_status, step="pre", color="#2c3e50", alpha=.8)
ax[5].set_ylabel("Pump ON/OFF", fontsize=8)
ax[5].set_ylim(-0.05, 1.05)
ax[0].set_title("Smart agriculture node - 21-day telemetry (all six ThingSpeak fields)")
save(fig, "01_timeseries_all_channels.png")

# 8.2 three-day zoom showing the irrigation control loop
z = df[(df.day_of_campaign >= 3) & (df.day_of_campaign < 6)]
fig, ax = plt.subplots(figsize=(12, 4.2))
ax.plot(z.timestamp, z.soil_moisture_pct, color="#8e6e3c", lw=1.1, label="Soil moisture")
ax.axhline(35, ls="--", c="r", lw=.9, label="Start set-point (35 %)")
ax.axhline(60, ls="--", c="g", lw=.9, label="Stop set-point (60 %)")
ax.fill_between(z.timestamp, 0, 100, where=z.pump_status == 1,
                color="#3498db", alpha=.16, label="Pump ON")
ax2 = ax.twinx()
ax2.plot(z.timestamp, z.temperature_c, color="#c0392b", lw=.8, alpha=.75, label="Temperature")
ax2.set_ylabel("Temperature (C)")
ax2.grid(False)
ax.set_ylim(20, 75)
ax.set_ylabel("Soil moisture (%)")
ax.set_title("Hysteresis irrigation loop - 3-day detail")
ax.legend(loc="upper left", fontsize=7, ncol=2)
save(fig, "02_control_loop_zoom.png")

# 8.3 correlation heat-map
fig, ax = plt.subplots(figsize=(8, 6.6))
m = ax.imshow(pearson.values, cmap="RdBu_r", vmin=-1, vmax=1)
ax.set_xticks(range(len(CORR_COLS)))
ax.set_xticklabels(CORR_COLS, rotation=55, ha="right", fontsize=7)
ax.set_yticks(range(len(CORR_COLS)))
ax.set_yticklabels(CORR_COLS, fontsize=7)
for i in range(len(CORR_COLS)):
    for j in range(len(CORR_COLS)):
        v = pearson.values[i, j]
        ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6,
                color="white" if abs(v) > .55 else "black")
ax.grid(False)
fig.colorbar(m, shrink=.8)
ax.set_title("Pearson correlation matrix")
save(fig, "03_correlation_heatmap.png")

# 8.4 diurnal profiles
fig, ax = plt.subplots(1, 3, figsize=(13, 3.4))
ax[0].plot(diurnal.index / 60, diurnal.temperature_c, color="#c0392b")
ax[0].plot(diurnal.index / 60, diurnal.humidity_pct, color="#2980b9")
ax[0].legend(["Temperature (C)", "Humidity (%)"], fontsize=7)
ax[0].set_xlabel("Hour of day")
ax[0].set_title("Mean diurnal cycle")
ax[1].plot(diurnal.index / 60, diurnal.light_pct, color="#f39c12")
ax[1].set_xlabel("Hour of day")
ax[1].set_title("Mean light intensity (%)")
ax[2].bar(pump_by_hour.index, pump_by_hour.values, color="#2c3e50")
ax[2].set_xlabel("Hour of day")
ax[2].set_ylabel("% of time pump ON")
ax[2].set_title("Irrigation activity by hour")
save(fig, "04_diurnal_profiles.png")

# 8.5 distributions
fig, ax = plt.subplots(1, 5, figsize=(15, 2.9))
for a, (c, lab, col) in zip(ax, series):
    a.hist(df[c], bins=60, color=col, alpha=.85)
    a.set_title(lab, fontsize=8)
save(fig, "05_distributions.png")

# 8.6 scatter: physical coupling
fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
s = df.sample(4000, random_state=0)
ax[0].scatter(s.temperature_c, s.humidity_pct, s=3, alpha=.25, c="#2980b9")
ax[0].set_xlabel("Temperature (C)"); ax[0].set_ylabel("Humidity (%)")
ax[0].set_title(f"T vs RH  (r = {pearson.loc['temperature_c','humidity_pct']:.2f})")
ax[1].scatter(s.vpd_hpa, -s.soil_rate_60 * 60, s=3, alpha=.25, c="#8e6e3c")
ax[1].set_xlabel("VPD (hPa)"); ax[1].set_ylabel("Drying rate (%/h)")
ax[1].set_title("Atmospheric demand vs drying rate")
ax[2].scatter(s.light_pct, s.temperature_c, s=3, alpha=.25, c="#f39c12")
ax[2].set_xlabel("Light (%)"); ax[2].set_ylabel("Temperature (C)")
ax[2].set_title(f"Light vs T  (r = {pearson.loc['light_pct','temperature_c']:.2f})")
save(fig, "06_physical_coupling.png")

# 8.7 injected faults on the timeline
fig, ax = plt.subplots(figsize=(12, 3.2))
ax.plot(df.timestamp, df.soil_moisture_pct, lw=.5, color="#8e6e3c")
an = df[df.is_anomaly == 1]
ax.scatter(an.timestamp, an.soil_moisture_pct, s=4, c="red", label="labelled fault window")
ax.set_ylabel("Soil moisture (%)")
ax.set_title("Injected sensor faults (ground truth for anomaly evaluation)")
ax.legend(fontsize=7)
save(fig, "07_injected_faults.png")


# ==========================================================================
# 9. PERSIST
# ==========================================================================
out = os.path.join(DATA, "processed_dataset.csv")
df.to_csv(out, index=False)

summary = {
    "rows": int(len(df)),
    "period": [str(df.timestamp.min()), str(df.timestamp.max())],
    "invalid_readings_repaired": n_bad_before,
    "descriptive": json.loads(desc.to_json(orient="index")),
    "pearson_sensors": json.loads(pearson.loc[SENSORS, SENSORS].round(4).to_json()),
    "temp_leads_drying_minutes": best_lag,
    "outlier_screening": outlier_tbl.to_dict(orient="records"),
    "statistical_detector_precision": round(prec, 4),
    "statistical_detector_recall": round(rec, 4),
    "class_balance": {
        "irrigation_required_pos_rate": round(float(df.irrigation_required.mean()), 4),
        "agronomic_demand_pos_rate": round(float(df.agronomic_demand.mean()), 4),
        "anomaly_rate": round(float(df.is_anomaly.mean()), 4),
    },
}
with open(os.path.join(DATA, "analytics_summary.json"), "w") as f:
    json.dump(summary, f, indent=2)

with open(os.path.join(REP, "analytics_tables.md"), "w") as f:
    f.write("# Stage-2 analytics tables\n\n## Descriptive statistics\n\n")
    f.write(desc.to_markdown())
    f.write("\n\n## Pearson correlation (sensors)\n\n")
    f.write(pearson.loc[SENSORS, SENSORS].round(3).to_markdown())
    f.write("\n\n## Spearman correlation (sensors)\n\n")
    f.write(spearman.loc[SENSORS, SENSORS].round(3).to_markdown())
    f.write("\n\n## Outlier screening\n\n")
    f.write(outlier_tbl.to_markdown(index=False))
    f.write("\n\n## Processing log\n\n")
    for line in log:
        f.write(f"- {line}\n")

print(f"\n[done] processed -> {out}")
print(f"[done] tables    -> {os.path.join(REP,'analytics_tables.md')}")
