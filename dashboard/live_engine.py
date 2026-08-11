r"""
live_engine.py
==============
Stateful, real-time version of the field node.

Why this file exists
--------------------
The trained models need 33-37 features, and most of them are HISTORY:
`soil_lag_60`, `soil_ma_120`, `soil_rate_15`, `temp_std_60`. You cannot compute
any of those from three slider values read at one instant. A dashboard that
takes three instantaneous numbers and calls `predict()` has to invent the other
thirty, and the confident number it prints is then derived from fabricated
inputs - which is worse than showing nothing.

So the live mode keeps STATE. Two objects:

  FieldSimulator   integrates the same water-balance / energy-balance model as
                   01_generate_dataset.py, one simulated minute per call, and
                   runs the same hysteresis controller the firmware runs.

  FeatureBuilder   holds a rolling buffer of recent readings and derives the
                   full feature row online, so every lag and rolling statistic
                   is genuine rather than reconstructed.

DEPLOYABILITY NOTE, worth a paragraph in the report:
an earlier version computed the 6-hour baselines with a CENTRED window, which
scored better (F1 0.453, ROC-AUC 0.879) but is not deployable - a centred window
needs future samples, so a live node cannot compute it. Stage 2 was changed to a
TRAILING window and M3 retrained, costing about 7 F1 points (F1 0.383, ROC-AUC
0.836). That is the real price of deployability, and paying it is what makes the
live features here bit-identical to the ones the model was trained on.
"""

from collections import deque
import numpy as np

# ---- control set-points: must match the firmware -------------------------
SM_LOW, SM_HIGH = 35.0, 60.0
TANK_MIN, TEMP_ALERT = 20.0, 35.0

# ---- hydrology constants: must match 01_generate_dataset.py --------------
THETA_FC, THETA_WP = 62.0, 9.0
PUMP_RECHARGE, DRAIN_K = 0.100, 0.060
TANK_DRAW, TANK_REFILL_RATE = 0.047, 3.0
TANK_H_CM, SENSOR_GAP_CM = 40.0, 4.0
ET_K = 0.0520

SENSORS = ["temperature_c", "humidity_pct", "soil_moisture_pct",
           "light_pct", "water_level_pct"]

BUFFER_MIN = 400          # must exceed the longest window (361) plus headroom

# 1st-99th percentile of the TRAINING period. Outside this envelope the models
# are extrapolating and their outputs should not be trusted; the UI says so
# rather than printing a confident number from an unseen region of input space.
TRAIN_RANGE = {
    "temperature_c":     (18.0, 40.0),
    "humidity_pct":      (22.0, 95.0),
    "soil_moisture_pct": (16.5, 67.5),
    "light_pct":         (0.0, 99.6),
    "water_level_pct":   (18.0, 95.8),
}


def out_of_distribution(reading):
    """Which channels sit outside the training envelope."""
    return [c for c, (lo, hi) in TRAIN_RANGE.items()
            if reading.get(c, lo) < lo or reading.get(c, lo) > hi]


def sat_vapour_pressure(t_c):
    return 6.112 * np.exp(17.67 * t_c / (t_c + 243.5))


# =========================================================================
#  FIELD SIMULATOR
# =========================================================================
class FieldSimulator:
    """One simulated minute per `step()`. Holds the true physical state."""

    def __init__(self, seed=7, start_minute=6 * 60, theta=48.0, tank=88.0):
        self.rng = np.random.default_rng(seed)
        self.t = int(start_minute)          # minutes since campaign start
        self.theta = float(theta)           # true soil moisture (%)
        self.tank = float(tank)             # true tank level (%)
        self.pump = 0
        self.cloud = 0.25
        self.q = 0.0115                     # specific humidity (kg/kg)
        self.weather = 0.0
        self.rain = 0.0
        self.rain_left = 0
        self.refilling = False

        # ---- FIELD controls: these change the physical state, so the water
        # balance and the controller both respond to them.
        self.temp_offset = 0.0        # degC added to true air temperature
        self.hum_offset = 0.0         # %RH added to true relative humidity
        self.hold_soil = None         # clamp true soil moisture to this value
        self.tank_override = None     # clamp true tank level to this value

        # ---- SENSOR controls: these corrupt only the reported reading, so the
        # controller keeps seeing the truth. This is the distinction the anomaly
        # detector exists to make, and the UI keeps the two groups apart.
        self.soil_bias = 0.0
        self.manual_pump = None             # None = automatic, 0/1 = forced
        self.fault = None                   # active injected fault
        self.fault_left = 0
        self._stuck_values = {}
        self._drift_accum = 0.0

    # ------------------------------------------------------------------
    @property
    def hour(self):
        return (self.t % 1440) / 60.0

    def _drivers(self):
        """Solar irradiance, air temperature, relative humidity, VPD."""
        h = self.hour
        sunrise, sunset = 6.2, 18.6
        if sunrise < h < sunset:
            clear = max(np.sin(np.pi * (h - sunrise) / (sunset - sunrise)), 0.0) ** 1.15
        else:
            clear = 0.0

        # cloud: mean-reverting, forced high during rain
        self.cloud += 0.0035 * (0.30 - self.cloud) + 0.022 * self.rng.standard_normal()
        if self.rain_left > 0:
            self.cloud = min(self.cloud + 0.55, 1.0)
        self.cloud = float(np.clip(self.cloud, 0.0, 1.0))

        irr = clear * (1.0 - 0.78 * self.cloud)

        day = self.t / 1440.0
        seasonal = 27.5 + 1.8 * np.sin(2 * np.pi * day / 30.0)
        diurnal = -np.cos(2 * np.pi * (h - 3.2) / 24.0)
        self.weather += 0.0025 * (0.0 - self.weather) + 0.055 * self.rng.standard_normal()
        temp = (seasonal + 6.4 * diurnal + 4.1 * irr - 1.6 * self.cloud
                + 3.0 * self.weather + 0.12 * self.rng.standard_normal())
        temp = float(np.clip(temp + self.temp_offset, 2.0, 48.0))

        self.q += 0.0030 * (0.0115 - self.q) + 0.00010 * self.rng.standard_normal()
        if self.rain_left > 0:
            self.q += 0.00004
        self.q = float(np.clip(self.q, 0.004, 0.024))

        P = 1000.0
        e = self.q * P / (0.622 + self.q)
        rh = float(np.clip(100.0 * e / sat_vapour_pressure(temp) + self.hum_offset,
                           8.0, 100.0))
        vpd = max(sat_vapour_pressure(temp) * (1 - rh / 100.0), 0.05)
        return irr, temp, rh, vpd

    def _et_rate(self, irr, temp, vpd):
        et0 = (ET_K * (0.22 + 0.78 * irr) * (1 + 0.030 * (temp - 25.0))
               * (0.35 + 0.65 * min(vpd / 22.0, 1.6)))
        ks = np.clip((self.theta - THETA_WP) / (0.45 * (THETA_FC - THETA_WP)), 0.0, 1.0)
        return max(et0 * ks, 0.0)

    def _control(self):
        """Same hysteresis law as the firmware."""
        if self.manual_pump is not None:
            self.pump = int(self.manual_pump)
            return
        if self.tank <= TANK_MIN:
            self.pump = 0
        elif self.theta < SM_LOW:
            self.pump = 1
        elif self.theta > SM_HIGH:
            self.pump = 0

    # ------------------------------------------------------------------
    def trigger_rain(self, minutes=45, peak=0.30):
        self.rain_left, self.rain = int(minutes), float(peak)

    def inject_fault(self, kind, minutes=45):
        self.fault, self.fault_left = kind, int(minutes)
        self._stuck_values, self._drift_accum = {}, 0.0

    def clear_fault(self):
        self.fault, self.fault_left = None, 0

    def refill_tank(self):
        self.refilling = True

    # ------------------------------------------------------------------
    def step(self):
        """Advance one simulated minute. Returns the reading the node would send."""
        irr, temp, rh, vpd = self._drivers()
        et = self._et_rate(irr, temp, vpd)

        rain_now = self.rain if self.rain_left > 0 else 0.0
        if self.rain_left > 0:
            self.rain_left -= 1

        self._control()

        # ---- water balance ------------------------------------------
        d_theta = (PUMP_RECHARGE * self.pump + rain_now - et
                   - DRAIN_K * max(self.theta - THETA_FC, 0.0))
        self.theta = float(np.clip(self.theta + d_theta, 4.0, 72.0))
        if self.hold_soil is not None:
            # operator is holding the field at a chosen moisture: the controller
            # and the water balance both see this, unlike a sensor bias
            self.theta = float(self.hold_soil)

        # ---- tank balance -------------------------------------------
        self.tank -= TANK_DRAW * self.pump + 0.0009
        if self.refilling:
            self.tank += TANK_REFILL_RATE
            if self.tank >= 95.0:
                self.tank, self.refilling = 95.0, False
        self.tank = float(np.clip(self.tank, 2.0, 100.0))

        self.t += 1

        # ---- sensor model: physics -> what the node reads ------------
        r = {
            "temperature_c": round(temp + 0.35 * self.rng.standard_normal()),
            "humidity_pct": round(rh + 1.4 * self.rng.standard_normal()),
            "soil_moisture_pct": self.theta + 0.55 * self.rng.standard_normal(),
            "light_pct": 100.0 * irr + 0.8 * self.rng.standard_normal(),
            "water_level_pct": self.tank + 0.75 * self.rng.standard_normal(),
            "pump_status": int(self.pump),
        }

        # ---- sensor-only corruption (controller is NOT fooled) -------
        r["soil_moisture_pct"] += self.soil_bias
        if self.tank_override is not None:
            r["water_level_pct"] = float(self.tank_override)
            self.tank = float(self.tank_override)

        # ---- injected fault -----------------------------------------
        truth_fault = 0
        if self.fault and self.fault_left > 0:
            truth_fault = 1
            k = self.fault
            if k == "spike":
                r["soil_moisture_pct"] += 32.0
            elif k == "stuck":
                for c in SENSORS:
                    self._stuck_values.setdefault(c, r[c])
                    r[c] = self._stuck_values[c]
            elif k == "drift":
                self._drift_accum += 0.35
                r["soil_moisture_pct"] += self._drift_accum
            elif k == "dropout":
                r["soil_moisture_pct"] = -999.0
            elif k == "phantom_wet":
                r["soil_moisture_pct"] += 24.0
            elif k == "tank_leak":
                self._drift_accum += 0.45
                r["water_level_pct"] -= self._drift_accum
            self.fault_left -= 1
            if self.fault_left == 0:
                self.fault = None

        # ---- clip to sensor range, leave the -999 sentinel intact ----
        for c in SENSORS:
            if r[c] > -900:
                lo, hi = (-10.0, 60.0) if c == "temperature_c" else (0.0, 100.0)
                r[c] = float(np.clip(r[c], lo, hi))

        r["minute"] = self.t
        r["is_fault"] = truth_fault
        r["fault_type"] = self.fault or ("none" if not truth_fault else "ending")
        r["true_soil"] = self.theta
        r["true_tank"] = self.tank
        r["et_rate"] = et
        r["rain"] = rain_now
        return r


# =========================================================================
#  ONLINE FEATURE BUILDER
# =========================================================================
class FeatureBuilder:
    """Rolling buffer -> the exact feature names the trained models expect."""

    def __init__(self, maxlen=BUFFER_MIN):
        self.buf = deque(maxlen=maxlen)
        self._flat = {c: 0 for c in SENSORS}
        self._last_valid = {}

    # ------------------------------------------------------------------
    def push(self, reading):
        """Apply the Layer-1 validity gate, then append. Returns (cleaned, flags)."""
        r = dict(reading)
        flags = {}
        for c in SENSORS:
            lo, hi = (-5.0, 60.0) if c == "temperature_c" else (0.0, 100.0)
            bad = (r[c] <= -900) or (r[c] < lo) or (r[c] > hi)
            flags[f"{c}_was_missing"] = int(bad)
            if bad:
                r[c] = self._last_valid.get(c, (lo + hi) / 2)   # hold last good
            else:
                self._last_valid[c] = r[c]

        # flat-run bookkeeping must use the cleaned series
        if self.buf:
            prev = self.buf[-1]
            for c in SENSORS:
                if flags[f"{c}_was_missing"]:
                    # value was held by the validity gate, not reported by the
                    # sensor - it must not count as evidence of a latched probe
                    self._flat[c] = 0
                else:
                    self._flat[c] = self._flat[c] + 1 if abs(r[c] - prev[c]) < 1e-9 else 0
        r["_flat"] = dict(self._flat)
        r["_flags"] = flags
        self.buf.append(r)
        return r, flags

    # ------------------------------------------------------------------
    def ready(self):
        return len(self.buf) >= 121          # enough for the 120-min windows

    def _series(self, col, n=None):
        vals = [b[col] for b in self.buf]
        return np.asarray(vals[-n:] if n else vals, dtype=float)

    def _lag(self, col, k):
        return float(self.buf[-1 - k][col]) if len(self.buf) > k else float(self.buf[0][col])

    # ------------------------------------------------------------------
    def features(self):
        """Full feature dict. Names match 02_preprocess_analyze.py exactly."""
        cur = self.buf[-1]
        f = {c: float(cur[c]) for c in SENSORS}
        f["pump_status"] = int(cur["pump_status"])

        # ---- time ----------------------------------------------------
        mod = cur["minute"] % 1440
        f["minute_of_day"] = float(mod)
        f["hour_sin"] = float(np.sin(2 * np.pi * mod / 1440))
        f["hour_cos"] = float(np.cos(2 * np.pi * mod / 1440))
        hour = mod / 60.0
        f["is_daytime"] = int(6.2 <= hour <= 18.6)

        # ---- lags ----------------------------------------------------
        for k in (5, 15, 30, 60):
            f[f"soil_lag_{k}"] = self._lag("soil_moisture_pct", k)
        for k in (15, 30):
            f[f"temp_lag_{k}"] = self._lag("temperature_c", k)
        f["hum_lag_15"] = self._lag("humidity_pct", 15)
        f["light_lag_15"] = self._lag("light_pct", 15)
        f["pump_lag_1"] = float(self.buf[-2]["pump_status"]) if len(self.buf) > 1 else 0.0
        f["pump_lag_15"] = float(self._lag("pump_status", 15))
        f["pump_on_last_60"] = float(self._series("pump_status", 60).sum())

        # ---- rates ---------------------------------------------------
        f["soil_rate_15"] = (f["soil_moisture_pct"] - f["soil_lag_15"]) / 15.0
        f["soil_rate_60"] = (f["soil_moisture_pct"] - f["soil_lag_60"]) / 60.0
        f["temp_rate_15"] = (f["temperature_c"] - f["temp_lag_15"]) / 15.0
        f["water_rate_30"] = (f["water_level_pct"]
                              - self._lag("water_level_pct", 30)) / 30.0

        # ---- rolling -------------------------------------------------
        f["soil_ma_30"] = float(self._series("soil_moisture_pct", 30).mean())
        f["soil_ma_120"] = float(self._series("soil_moisture_pct", 120).mean())
        f["temp_ma_30"] = float(self._series("temperature_c", 30).mean())
        f["temp_ma_120"] = float(self._series("temperature_c", 120).mean())
        f["light_ma_120"] = float(self._series("light_pct", 120).mean())
        f["temp_std_60"] = float(self._series("temperature_c", 60).std(ddof=1))
        f["soil_std_60"] = float(self._series("soil_moisture_pct", 60).std(ddof=1))

        # ---- physics -------------------------------------------------
        es = sat_vapour_pressure(f["temperature_c"])
        f["vpd_hpa"] = float(max(es * (1 - f["humidity_pct"] / 100.0), 0.0))
        f["heat_index_proxy"] = f["temperature_c"] * (1 + 0.01 * (100 - f["humidity_pct"]))
        f["et_proxy"] = f["vpd_hpa"] * (0.25 + 0.75 * f["light_pct"] / 100.0)
        f["water_available"] = int(f["water_level_pct"] > TANK_MIN)
        f["deficit_from_target"] = SM_HIGH - f["soil_moisture_pct"]

        # ---- anomaly-facing view -------------------------------------
        # TRAILING windows, not centred: this is the online formulation.
        for c in SENSORS:
            f[f"{c}_flat_run"] = float(min(cur["_flat"][c], 180))
            win = self._series(c, 361)
            f[f"{c}_dev_360"] = float(f[c] - np.median(win))
        for c in ("soil_moisture_pct", "humidity_pct", "water_level_pct"):
            d = np.diff(self._series(c, 61))
            f[f"{c}_mono60"] = float(np.sign(d).mean()) if len(d) else 0.0

        e = es * f["humidity_pct"] / 100.0
        q_now = 0.622 * e / (1000.0 - e)
        q_hist = []
        for b in list(self.buf)[-361:]:
            es_b = sat_vapour_pressure(b["temperature_c"])
            e_b = es_b * b["humidity_pct"] / 100.0
            q_hist.append(0.622 * e_b / (1000.0 - e_b))
        f["q_dev_360"] = float(q_now - np.median(q_hist))

        pump_min_30 = float(self._series("pump_status", 30).sum())
        soil_delta_30 = f["soil_moisture_pct"] - self._lag("soil_moisture_pct", 30)
        water_delta_30 = f["water_level_pct"] - self._lag("water_level_pct", 30)
        # coefficients from the week-1 least-squares calibration in stage 2
        expected = 0.0980 * pump_min_30 - 0.06480 * f["et_proxy"] + 0.0012
        f["hydro_residual"] = float(soil_delta_30 - expected)
        f["tank_residual"] = float(water_delta_30 + 0.047 * pump_min_30)

        return f


# =========================================================================
def warm_up(sim, fb, minutes=420):
    """Run the simulator headless so the buffer is full before the UI starts."""
    for _ in range(minutes):
        fb.push(sim.step())
    return sim, fb
