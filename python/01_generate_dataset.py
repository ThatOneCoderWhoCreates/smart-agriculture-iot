r"""
01_generate_dataset.py
======================
Physics-based simulator for the IoT Smart Agriculture testbed.

This is NOT a random-number generator. Every channel is produced by a coupled
model of the field micro-climate, so the correlations that the ML stage later
"discovers" are physically real:

    solar irradiance  ->  air temperature  ->  vapour-pressure deficit
                      \                     \
                       ->  evapotranspiration (ET) -> soil moisture depletion
    irrigation pump   ->  soil moisture recharge, tank drawdown
    rainfall          ->  soil recharge + humidity spike + irradiance drop

Governing soil-water balance (per minute, root-zone depth-averaged):

    d(theta)/dt = I(t) + R(t) - ET(t) - D(theta)

    I(t)   irrigation recharge rate  (pump ON)
    R(t)   rainfall infiltration rate
    ET(t)  evapotranspiration, FAO-56 style: ET0 * Ks(theta)
    D()    gravitational drainage above field capacity

Outputs
-------
    data/sensor_data_raw.csv      "as transmitted by the node" (noisy, ADC-quantised,
                                  contains injected faults, -999 dropouts)
    data/ground_truth.csv         clean physical state + anomaly labels (for evaluation only)

Run:  python 01_generate_dataset.py
"""

import os
import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# 0. CONFIGURATION
# --------------------------------------------------------------------------
SEED               = 42
DAYS               = 21            # length of the logged campaign
SAMPLE_MIN         = 1             # sampling period (minutes)
START               = pd.Timestamp("2026-03-01 00:00:00")

# --- Irrigation control set-points (must match the Arduino firmware) -------
SM_LOW             = 35.0          # % -> start irrigation below this
SM_HIGH            = 60.0          # % -> stop  irrigation above this
TANK_MIN           = 20.0          # % -> pump inhibited below this
TEMP_ALERT         = 35.0          # degC -> high-temperature warning

# --- Soil hydrology --------------------------------------------------------
THETA_FC           = 62.0          # field capacity (%)
THETA_WP           = 9.0           # permanent wilting point (%)
PUMP_RECHARGE      = 0.100         # %/min added to root zone while pump ON
DRAIN_K            = 0.060         # gravitational drainage coefficient

# --- Tank ------------------------------------------------------------------
TANK_DRAW          = 0.047         # % of tank volume consumed per minute of pumping
TANK_REFILL_RATE   = 3.0           # %/min while refilling
TANK_REFILL_HOUR   = 5             # scheduled top-up time
TANK_REFILL_BELOW  = 55.0          # only top up if below this
TANK_H_CM          = 40.0          # physical tank height for HC-SR04 mapping
SENSOR_OFFSET_CM   = 4.0           # ultrasonic sensor sits this far above full mark

MAD_H = 120.0      # agronomic look-ahead used inside the integrator

# --- Anomaly injection -----------------------------------------------------
# fault schedule below is fixed by count/duration; observed rate ~5 % of samples

rng = np.random.default_rng(SEED)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)


# --------------------------------------------------------------------------
# 1. HELPERS
# --------------------------------------------------------------------------
def ou_process(n, theta, sigma, x0=0.0):
    """Ornstein-Uhlenbeck (mean-reverting) noise -> smooth 'weather' wander."""
    x = np.empty(n)
    x[0] = x0
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (0.0 - x[i - 1]) + sigma * rng.standard_normal()
    return x


def sat_vapour_pressure(t_c):
    """Magnus-Tetens saturation vapour pressure (hPa)."""
    return 6.112 * np.exp(17.67 * t_c / (t_c + 243.5))


def adc_quantise(value, vmin, vmax, bits=10):
    """Emulate a 10-bit ADC: continuous physics -> integer counts -> back."""
    levels = (1 << bits) - 1
    counts = np.clip(np.round((value - vmin) / (vmax - vmin) * levels), 0, levels)
    return counts, vmin + counts / levels * (vmax - vmin)


# --------------------------------------------------------------------------
# 2. TIME BASE AND EXOGENOUS DRIVERS
# --------------------------------------------------------------------------
N = int(DAYS * 24 * 60 / SAMPLE_MIN)
ts = pd.date_range(START, periods=N, freq=f"{SAMPLE_MIN}min")
hour = ts.hour.values + ts.minute.values / 60.0
day_idx = np.arange(N) * SAMPLE_MIN / 1440.0

SUNRISE, SUNSET = 6.2, 18.6

# ---- clear-sky irradiance -------------------------------------------------
day_shape = np.sin(np.pi * (hour - SUNRISE) / (SUNSET - SUNRISE))
clear_sky = np.where((hour > SUNRISE) & (hour < SUNSET), np.clip(day_shape, 0, 1) ** 1.15, 0.0)

# ---- cloud cover (0 = clear, 1 = overcast) --------------------------------
cloud = np.clip(0.30 + ou_process(N, 0.0035, 0.022), 0.0, 1.0)

# ---- rainfall events (Poisson-ish, 20-90 min duration) --------------------
rain_rate = np.zeros(N)                       # %/min infiltration into root zone
i = 0
while i < N:
    gap = int(rng.exponential(3.2 * 1440))    # mean one event every ~3.2 days
    i += max(gap, 400)
    if i >= N:
        break
    dur = int(rng.uniform(20, 95))
    peak = rng.uniform(0.10, 0.45)
    prof = np.sin(np.linspace(0, np.pi, dur)) ** 0.6
    end = min(i + dur, N)
    rain_rate[i:end] += peak * prof[: end - i]
    cloud[max(0, i - 60): min(N, end + 90)] = np.clip(
        cloud[max(0, i - 60): min(N, end + 90)] + 0.55, 0, 1)
    i = end

irradiance = clear_sky * (1.0 - 0.78 * cloud)          # 0..1 normalised
lux = 92000.0 * irradiance + rng.normal(0, 120, N).clip(0)

# ---- air temperature ------------------------------------------------------
seasonal = 27.5 + 1.8 * np.sin(2 * np.pi * day_idx / 30.0)
diurnal = -np.cos(2 * np.pi * (hour - 3.2) / 24.0)      # peaks ~15:00
weather = ou_process(N, 0.0025, 0.055) * 3.0
temp = seasonal + 6.4 * diurnal + 4.1 * irradiance - 1.6 * cloud + weather
# two engineered heat-wave days -> guarantees the >35 degC alert scenario
for d in (8, 15):
    m = (day_idx >= d) & (day_idx < d + 1.1)
    temp[m] += 3.4 * np.clip(np.sin(np.pi * (day_idx[m] - d) / 1.1), 0, 1)
temp += rng.normal(0, 0.12, N)

# ---- humidity from specific humidity + Magnus ------------------------------
q = np.clip(0.0115 + ou_process(N, 0.0030, 0.00010), 0.004, 0.024)   # kg/kg
q += np.convolve(rain_rate, np.ones(90) / 90.0, mode="same") * 0.0022
P = 1000.0                                                          # hPa
e = q * P / (0.622 + q)
rh = np.clip(100.0 * e / sat_vapour_pressure(temp), 14.0, 99.0)
rh += rng.normal(0, 0.6, N)
rh = np.clip(rh, 10, 96)

# vapour-pressure deficit -> the real driver of ET
vpd = np.clip(sat_vapour_pressure(temp) * (1 - rh / 100.0), 0.05, None)


# --------------------------------------------------------------------------
# 3. COUPLED STATE INTEGRATION (soil water, tank, pump controller)
# --------------------------------------------------------------------------
theta = np.empty(N)          # true soil moisture (%)
tank = np.empty(N)           # true tank level (%)
pump = np.zeros(N, dtype=int)
et = np.empty(N)             # ET rate (%/min)
theta_proj = np.empty(N)     # projected theta at t+30 min under NO irrigation

theta[0], tank[0] = 48.0, 92.0
refilling = False
# deliberately skip the scheduled refill on days 12-13 -> low-tank scenario
SKIP_REFILL_DAYS = {11, 12, 13, 14}

ET_K = 0.0520                # calibrated so peak depletion ~ 30-40 %/day


def et_rate(i):
    """FAO-56 flavoured: reference ET scaled by a soil water stress factor Ks."""
    et0 = ET_K * (0.22 + 0.78 * irradiance[i]) * (1 + 0.030 * (temp[i] - 25.0)) \
                * (0.35 + 0.65 * np.clip(vpd[i] / 22.0, 0, 1.6))
    ks = np.clip((theta[i] - THETA_WP) / (0.45 * (THETA_FC - THETA_WP)), 0.0, 1.0)
    return max(et0 * ks, 0.0)


for i in range(N):
    et[i] = et_rate(i)

    # ---- hysteresis irrigation controller (mirrors the Arduino logic) -----
    if tank[i] <= TANK_MIN:
        pump[i] = 0
    elif theta[i] < SM_LOW:
        pump[i] = 1
    elif theta[i] > SM_HIGH:
        pump[i] = 0
    else:
        pump[i] = pump[i - 1] if i > 0 else 0

    # ---- 30-min lookahead assuming the pump stays OFF (label engineering) --
    drain_now = DRAIN_K * max(theta[i] - THETA_FC, 0.0)
    theta_proj[i] = theta[i] - MAD_H * (et[i] + drain_now) + MAD_H * rain_rate[i]

    if i == N - 1:
        break

    # ---- water balance ----------------------------------------------------
    d_theta = (PUMP_RECHARGE * pump[i]) + rain_rate[i] - et[i] \
              - DRAIN_K * max(theta[i] - THETA_FC, 0.0)
    theta[i + 1] = np.clip(theta[i] + d_theta * SAMPLE_MIN, 4.0, 72.0)

    # ---- tank balance -----------------------------------------------------
    t_next = tank[i] - TANK_DRAW * pump[i] * SAMPLE_MIN
    t_next -= 0.0009 * SAMPLE_MIN                       # evaporation from tank
    day_num = int(day_idx[i])
    at_refill_time = (ts[i].hour == TANK_REFILL_HOUR and ts[i].minute == 0)
    if at_refill_time and tank[i] < TANK_REFILL_BELOW and day_num not in SKIP_REFILL_DAYS:
        refilling = True
    if refilling:
        t_next += TANK_REFILL_RATE * SAMPLE_MIN
        if t_next >= 95.0:
            t_next, refilling = 95.0, False
    tank[i + 1] = np.clip(t_next, 2.0, 100.0)

# emergency top-up if the tank ever bottoms out for too long (day 14 recovery)
# handled implicitly by the day-14 scheduled refill.


# --------------------------------------------------------------------------
# 4. LABEL ENGINEERING
# --------------------------------------------------------------------------
HORIZON = 30    # minutes (regression + classification lookahead)
MAD_HORIZON = 120  # minutes (agronomic demand lookahead)

# (a) PRIMARY target for the classifier: will irrigation be required in 30 min?
#     Defined as the *controller* demand state 30 min ahead. Predicting this
#     lets the edge node pre-position the pump instead of reacting late.
irrigation_required = np.roll(pump, -HORIZON)
irrigation_required[-HORIZON:] = pump[-HORIZON:]

# (b) AGRONOMIC demand label (used as a secondary / discussion target):
#     soil water would cross the management-allowed-depletion line within 30 min.
agronomic_demand = ((theta_proj < SM_LOW) & (tank > TANK_MIN)).astype(int)

# (c) NAIVE rule label = literal restatement of the current rule.
#     Kept only to demonstrate in the report that it is tautological (~100 % acc).
naive_rule = ((theta < SM_LOW) & (tank > TANK_MIN)).astype(int)

# (d) REGRESSION target: actual soil moisture 30 min into the future
soil_future_30 = np.roll(theta, -HORIZON)
soil_future_30[-HORIZON:] = np.nan


# --------------------------------------------------------------------------
# 5. SENSOR MODEL  (true physics -> what the microcontroller actually reads)
# --------------------------------------------------------------------------
temp_m = temp + rng.normal(0, 0.35, N)                 # DHT11 +/- 2 degC spec, 1 degC res
temp_m = np.round(temp_m)                              # DHT11 integer resolution
rh_m = np.round(rh + rng.normal(0, 1.4, N))            # DHT11 +/- 5 % RH

sm_counts, sm_m = adc_quantise(theta + rng.normal(0, 0.55, N), 0, 100)
ldr_counts, light_m = adc_quantise(100.0 * irradiance + rng.normal(0, 0.8, N), 0, 100)

# HC-SR04: measure air gap, convert to level. +/-3 mm noise, 1 cm quantisation.
dist_cm = SENSOR_OFFSET_CM + (1 - tank / 100.0) * TANK_H_CM + rng.normal(0, 0.30, N)
dist_cm = np.round(dist_cm, 1)
water_m = np.clip((1 - (dist_cm - SENSOR_OFFSET_CM) / TANK_H_CM) * 100.0, 0, 100)

frames = {
    "timestamp": ts,
    "temperature_c": temp_m,
    "humidity_pct": np.clip(rh_m, 0, 100),
    "soil_moisture_pct": np.round(sm_m, 2),
    "light_pct": np.round(light_m, 2),
    "water_level_pct": np.round(water_m, 2),
    "pump_status": pump,
}
df = pd.DataFrame(frames)


# --------------------------------------------------------------------------
# 6. FAULT / ANOMALY INJECTION
# --------------------------------------------------------------------------
is_anom = np.zeros(N, dtype=int)
anom_type = np.array(["none"] * N, dtype=object)

SENSOR_COLS = ["temperature_c", "humidity_pct", "soil_moisture_pct",
               "light_pct", "water_level_pct"]


def stamp(a, b, label):
    is_anom[a:b] = 1
    anom_type[a:b] = label


# Planned fault schedule: a fixed budget per fault class so that every failure
# mode is represented (an opportunistic random loop starves the rare classes).
PLAN = [("spike", 18), ("dropout", 14), ("stuck", 8),
        ("drift", 4), ("phantom_wet", 5), ("tank_leak", 4)]
plan = [k for k, n_ev in PLAN for _ in range(n_ev)]
rng.shuffle(plan)

used = 0
for kind in plan:
    placed = False
    for _ in range(60):                                   # retry until a free slot is found
        start = int(rng.integers(180, N - 500))
        if is_anom[max(0, start - 45):start + 380].any():
            continue
        placed = True
        break
    if not placed:
        continue

    if kind == "spike":                                   # transient electrical spike
        col = rng.choice(SENSOR_COLS)
        dur = int(rng.integers(1, 6))
        sign = rng.choice([-1, 1])
        mag = rng.uniform(2.5, 5.5) * df[col].std()
        df.loc[start:start + dur - 1, col] += sign * mag
        stamp(start, start + dur, f"spike:{col}")
        used += dur

    elif kind == "stuck":                                 # frozen / latched reading
        col = rng.choice(SENSOR_COLS)
        dur = int(rng.integers(30, 80))
        df.loc[start:start + dur - 1, col] = df.loc[start, col]
        stamp(start, start + dur, f"stuck:{col}")
        used += dur

    elif kind == "drift":                                 # calibration drift / fouling
        col = rng.choice(["soil_moisture_pct", "humidity_pct", "water_level_pct"])
        dur = int(rng.integers(100, 170))
        ramp = np.linspace(0, rng.choice([-1, 1]) * rng.uniform(12, 26), dur)
        df.loc[start:start + dur - 1, col] += ramp
        stamp(start, start + dur, f"drift:{col}")
        used += dur

    elif kind == "dropout":                               # bus / wiring failure
        col = rng.choice(SENSOR_COLS)
        dur = int(rng.integers(3, 30))
        df.loc[start:start + dur - 1, col] = -999.0
        stamp(start, start + dur, f"dropout:{col}")
        used += dur

    elif kind == "phantom_wet":                           # physically impossible jump
        dur = int(rng.integers(20, 60))
        for _ in range(80):                               # need a pump-off, rain-free window
            if (pump[start:start + dur].sum() == 0
                    and rain_rate[start:start + dur].sum() == 0
                    and not is_anom[max(0, start - 45):start + dur + 45].any()):
                break
            start = int(rng.integers(180, N - 500))
        df.loc[start:start + dur - 1, "soil_moisture_pct"] += rng.uniform(16, 30)
        stamp(start, start + dur, "phantom_wet:soil")
        used += dur

    else:                                                 # tank_leak (pump OFF but level falls)
        dur = int(rng.integers(45, 105))
        for _ in range(80):
            if (pump[start:start + dur].sum() == 0
                    and not is_anom[max(0, start - 45):start + dur + 45].any()):
                break
            start = int(rng.integers(180, N - 500))
        leak = np.linspace(0, rng.uniform(15, 32), dur)
        df.loc[start:start + dur - 1, "water_level_pct"] -= leak
        stamp(start, start + dur, "tank_leak:water")
        used += dur

# clip back into physical sensor range, but leave -999 dropouts intact
for c in SENSOR_COLS:
    v = df[c].to_numpy(copy=True)
    hi = 60.0 if c == "temperature_c" else 100.0
    lo = -10.0 if c == "temperature_c" else 0.0
    mask = v > -900
    v[mask] = np.clip(v[mask], lo, hi)
    df[c] = v

df["is_anomaly"] = is_anom
df["anomaly_type"] = anom_type


# --------------------------------------------------------------------------
# 7. DERIVED STATUS FLAGS AND LABELS (what the node would also publish)
# --------------------------------------------------------------------------
df["low_water_alert"] = (tank <= TANK_MIN).astype(int)
df["high_temp_alert"] = (temp >= TEMP_ALERT).astype(int)
df["irrigation_required"] = irrigation_required
df["agronomic_demand"] = agronomic_demand
df["naive_rule_label"] = naive_rule
df["soil_moisture_future_30"] = np.round(soil_future_30, 3)

gt = pd.DataFrame({
    "timestamp": ts,
    "true_temperature_c": np.round(temp, 3),
    "true_humidity_pct": np.round(rh, 3),
    "true_soil_moisture_pct": np.round(theta, 3),
    "true_light_pct": np.round(100 * irradiance, 3),
    "true_water_level_pct": np.round(tank, 3),
    "irradiance": np.round(irradiance, 4),
    "lux": np.round(lux, 1),
    "vpd_hpa": np.round(vpd, 3),
    "et_rate_pct_per_min": np.round(et, 5),
    "rain_rate": np.round(rain_rate, 4),
    "cloud": np.round(cloud, 4),
    "theta_proj_30_no_irrigation": np.round(theta_proj, 3),
    "pump_status": pump,
    "is_anomaly": is_anom,
    "anomaly_type": anom_type,
})

raw_path = os.path.join(DATA, "sensor_data_raw.csv")
gt_path = os.path.join(DATA, "ground_truth.csv")
df.to_csv(raw_path, index=False)
gt.to_csv(gt_path, index=False)


# --------------------------------------------------------------------------
# 8. SUMMARY
# --------------------------------------------------------------------------
transitions = int(np.abs(np.diff(pump)).sum() / 2)
print("=" * 68)
print("DATASET GENERATED")
print("=" * 68)
print(f"rows                     : {N:,}  ({DAYS} days @ {SAMPLE_MIN} min)")
print(f"period                   : {ts[0]}  ->  {ts[-1]}")
print(f"temperature  (true)      : {temp.min():5.1f} .. {temp.max():5.1f} degC")
print(f"humidity     (true)      : {rh.min():5.1f} .. {rh.max():5.1f} %")
print(f"soil moisture(true)      : {theta.min():5.1f} .. {theta.max():5.1f} %")
print(f"water level  (true)      : {tank.min():5.1f} .. {tank.max():5.1f} %")
print(f"pump duty cycle          : {100*pump.mean():5.2f} %")
print(f"irrigation events        : {transitions}")
print(f"rain events (minutes)    : {int((rain_rate>0).sum())}")
print(f"high-temp alert samples  : {int(df.high_temp_alert.sum())}")
print(f"low-water alert samples  : {int(df.low_water_alert.sum())}")
print(f"anomalous samples        : {int(is_anom.sum())}  ({100*is_anom.mean():.2f} %)")
print(f"label 'irrigation_required' positive rate : {100*irrigation_required.mean():.2f} %")
print(f"label 'agronomic_demand'    positive rate : {100*agronomic_demand.mean():.2f} %")
print(f"\nwritten -> {raw_path}")
print(f"written -> {gt_path}")
