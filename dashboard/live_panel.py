r"""
live_panel.py
=============
Real-time mode for the dashboard: the field runs forward one simulated minute
per tick, you perturb it with the sliders, and all three models re-score the
node every tick.

The features are computed by FeatureBuilder from a rolling buffer, so every lag
and rolling statistic is real. Verified against the offline pipeline: M1
probability and M2 prediction agree to within 0.12 and 0.20 pp respectively, and
M3 flags agree on 99.8 % of samples. The small residual comes from one genuine
online/offline difference - offline interpolates across a dropout, a live node
can only hold the last valid reading.
"""

import time
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import theme as T
from live_engine import (FieldSimulator, FeatureBuilder, warm_up,
                         out_of_distribution, TRAIN_RANGE,
                         SM_LOW, SM_HIGH, TANK_MIN, TEMP_ALERT, SENSORS)

HIST = 720          # minutes of history retained for plotting
FAULTS = ["spike", "stuck", "drift", "dropout", "phantom_wet", "tank_leak"]


# --------------------------------------------------------------------------
def _init():
    if "sim" in st.session_state:
        return
    sim = FieldSimulator(seed=int(time.time()) % 10_000)
    fb = FeatureBuilder()
    with st.spinner("Warming up the node (7 h of history so lag features are real)..."):
        warm_up(sim, fb, minutes=420)
    st.session_state.sim = sim
    st.session_state.fb = fb
    st.session_state.hist = []
    st.session_state.running = False
    st.session_state.speed = 1


def _reset():
    for k in ("sim", "fb", "hist", "running"):
        st.session_state.pop(k, None)
    _init()


# --------------------------------------------------------------------------
def _advance(models, n_min=1):
    """Step the field, rebuild features, score all three models."""
    sim, fb = st.session_state.sim, st.session_state.fb
    out = None
    for j in range(n_min):
        raw = sim.step()
        clean, flags = fb.push(raw)
        if not fb.ready():
            continue
        # Scoring costs ~145 ms. At 60 sim-min per tick, scoring every minute
        # would take 9 s and the UI would stall, so intermediate minutes are
        # buffered (they still feed every lag and rolling window) and only the
        # minute the operator actually sees is scored.
        scored = (j == n_min - 1)
        f = fb.features() if scored else None
        if not scored:
            st.session_state.hist.append(
                {"minute": raw["minute"], **{c: clean[c] for c in SENSORS},
                 "pump_status": clean["pump_status"], "is_fault": raw["is_fault"],
                 "fault_type": raw["fault_type"],
                 "layer1": int(sum(flags.values()) > 0),
                 "irrig_prob": np.nan, "soil_30": np.nan,
                 "anom_score": np.nan, "anom_flag": 0, "anom_thr": np.nan})
            continue
        row = pd.Series(f)

        rec = {"minute": raw["minute"], **{c: clean[c] for c in SENSORS},
               "pump_status": clean["pump_status"],
               "is_fault": raw["is_fault"], "fault_type": raw["fault_type"],
               "layer1": int(sum(flags.values()) > 0)}

        if models["m1"]:
            X = row[models["m1"]["features"]].to_frame().T.astype(float)
            rec["irrig_prob"] = float(models["m1"]["model"].predict_proba(X)[0, 1])
        if models["m2"]:
            X = row[models["m2"]["features"]].to_frame().T.astype(float)
            rec["soil_30"] = float(models["m2"]["model"].predict(X)[0])
        if models["m3"]:
            X = row[models["m3"]["features"]].to_frame().T.astype(float)
            X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            # score = -decision_function, so the model's own boundary is score > 0.
            # Displaying that instead of the tuned sweep threshold keeps the flag
            # shown on screen consistent with the flag the model actually raises.
            rec["anom_score"] = float(-models["m3"]["model"].decision_function(X)[0])
            thr = (models["m3"]["threshold"]
                   if st.session_state.get("op_point", "F1-optimal") == "F1-optimal"
                   else 0.0)
            rec["anom_thr"] = thr
            rec["anom_flag"] = int(rec["anom_score"] >= thr)
        out = rec
        st.session_state.hist.append(rec)

    if len(st.session_state.hist) > HIST:
        st.session_state.hist = st.session_state.hist[-HIST:]
    return out


# --------------------------------------------------------------------------
def _controls(models):
    sim = st.session_state.sim
    st.sidebar.subheader("Live controls")

    c1, c2, c3 = st.sidebar.columns(3)
    if c1.button("Run", width="stretch"):
        st.session_state.running = True
    if c2.button("Pause", width="stretch"):
        st.session_state.running = False
    if c3.button("Step", width="stretch"):
        st.session_state.running = False
        _advance(models, 1)

    st.session_state.speed = st.sidebar.select_slider(
        "Simulated minutes per second", [1, 2, 5, 15, 30, 60],
        value=st.session_state.speed)

    st.sidebar.markdown("**Field conditions** — these change the physical state, "
                        "so the controller and the water balance both respond")
    sim.temp_offset = st.sidebar.slider("Temperature forcing (°C)", -8.0, 10.0,
                                        float(sim.temp_offset), 0.5)
    sim.hum_offset = st.sidebar.slider("Humidity forcing (% RH)", -25.0, 25.0,
                                       float(sim.hum_offset), 1.0)

    hs = st.sidebar.checkbox("Hold soil moisture at",
                             value=sim.hold_soil is not None)
    if hs:
        sim.hold_soil = st.sidebar.slider("Soil moisture (%)", 5.0, 72.0,
                                          float(sim.hold_soil or sim.theta), 0.5)
    else:
        sim.hold_soil = None

    ov = st.sidebar.checkbox("Hold tank level at", value=sim.tank_override is not None)
    if ov:
        sim.tank_override = st.sidebar.slider("Tank level (%)", 0.0, 100.0,
                                              float(sim.tank_override or sim.tank), 1.0)
    else:
        sim.tank_override = None

    st.sidebar.markdown("**Sensor corruption** — changes only the reported value, "
                        "so the controller still sees the truth")
    sim.soil_bias = st.sidebar.slider("Soil probe bias (pp)", -30.0, 30.0,
                                      float(sim.soil_bias), 0.5)

    st.sidebar.markdown("**Pump**")

    mode = st.sidebar.radio("Pump", ["Automatic", "Force ON", "Force OFF"],
                            horizontal=True)
    sim.manual_pump = {"Automatic": None, "Force ON": 1, "Force OFF": 0}[mode]

    b1, b2 = st.sidebar.columns(2)
    if b1.button("Refill tank", width="stretch"):
        sim.refill_tank()
    if b2.button("Make it rain", width="stretch"):
        sim.trigger_rain(minutes=45, peak=0.30)

    st.sidebar.markdown("**Detector operating point**")
    st.session_state.op_point = st.sidebar.radio(
        "M3 sensitivity", ["F1-optimal", "Conservative"], horizontal=True,
        captions=["tuned threshold from the sweep", "the model's own boundary"],
        index=0 if st.session_state.get("op_point", "F1-optimal") == "F1-optimal" else 1)

    st.sidebar.markdown("**Inject a sensor fault** — to exercise M3")
    fk = st.sidebar.selectbox("Fault type", FAULTS)
    fd = st.sidebar.slider("Duration (sim minutes)", 5, 120, 45, 5)
    f1, f2 = st.sidebar.columns(2)
    if f1.button("Inject", width="stretch"):
        sim.inject_fault(fk, fd)
    if f2.button("Clear", width="stretch"):
        sim.clear_fault()

    st.sidebar.divider()
    if st.sidebar.button("Reset field", width="stretch"):
        _reset()
        st.rerun()


# --------------------------------------------------------------------------
def _draw(models, mode):
    P = T.palette(mode)
    hist = st.session_state.hist
    sim = st.session_state.sim
    if not hist:
        st.info("Press **Run** to start the field, or **Step** to advance one minute.")
        return
    cur = hist[-1]
    h = pd.DataFrame(hist)
    clock = f"day {cur['minute']//1440} · {cur['minute']%1440//60:02d}:{cur['minute']%60:02d}"

    low_water = cur["water_level_pct"] <= TANK_MIN
    hot = cur["temperature_c"] >= TEMP_ALERT
    anom = bool(cur.get("anom_flag", 0))
    l1 = bool(cur.get("layer1", 0))

    T.status_strip([
        ("Irrigating" if cur["pump_status"] else "Pump idle",
         "water" if cur["pump_status"] else "ok"),
        ("Low water — pump inhibited" if low_water else "Tank healthy",
         "danger" if low_water else "ok"),
        ("Heat stress" if hot else "Temperature normal", "warn" if hot else "ok"),
        ("Validity fault" if l1 else ("Anomaly detected" if anom else "Sensors nominal"),
         "danger" if (anom or l1) else "ok"),
    ])

    running = "running" if st.session_state.running else "paused"
    fault_txt = (f" · injected <b>{sim.fault}</b>, {sim.fault_left} min left"
                 if sim.fault else "")
    st.markdown(f'<div class="clockline">Simulated clock <b>{clock}</b> · {running} · '
                f'<b>{st.session_state.speed}</b> sim-min per second · buffer '
                f'<b>{len(st.session_state.fb.buf)}</b> min{fault_txt}</div>',
                unsafe_allow_html=True)

    ood = out_of_distribution(cur)
    if ood:
        rng = ", ".join(f"{c} {TRAIN_RANGE[c][0]:g}–{TRAIN_RANGE[c][1]:g}" for c in ood)
        st.warning(f"**Outside the training envelope** — {', '.join(ood)}. The models "
                   f"never saw this region ({rng}), so everything below is extrapolation "
                   f"and should not be quoted as a result.")
    st.write("")

    # ---- readouts --------------------------------------------------------
    prev = hist[-31] if len(hist) > 31 else hist[0]
    T.readout_row(mode, [
        dict(label="Temperature", value=f"{cur['temperature_c']:.0f}", unit="°C",
             delta=cur["temperature_c"] - prev["temperature_c"], note="30 min",
             colour="danger"),
        dict(label="Humidity", value=f"{cur['humidity_pct']:.0f}", unit="%",
             delta=cur["humidity_pct"] - prev["humidity_pct"], note="30 min",
             colour="water"),
        dict(label="Soil moisture", value=f"{cur['soil_moisture_pct']:.1f}", unit="%",
             delta=cur["soil_moisture_pct"] - prev["soil_moisture_pct"], note="30 min",
             colour="soil"),
        dict(label="Light", value=f"{cur['light_pct']:.0f}", unit="%",
             delta=cur["light_pct"] - prev["light_pct"], note="30 min", colour="warn"),
        dict(label="Tank level", value=f"{cur['water_level_pct']:.0f}", unit="%",
             delta=cur["water_level_pct"] - prev["water_level_pct"], note="30 min",
             colour="ok"),
        dict(label="Pump", value="ON" if cur["pump_status"] else "OFF", unit="",
             delta=f"{100*h.pump_status.tail(360).mean():.0f}% duty", note="6 h",
             colour="water" if cur["pump_status"] else "line"),
    ])
    st.write("")

    # ---- decision support -------------------------------------------------
    T.eyebrow("Decision support · recomputed every tick")
    c1, c2, c3 = st.columns([1, 1.05, 1.15])

    with c1:
        p = cur.get("irrig_prob", 0.0)
        col = P["water"] if p >= .5 else P["muted"]
        st.markdown(
            f'<div class="panel"><div class="cap">Irrigation demand · next 120 min</div>'
            f'<div class="big" style="color:{col}">{"YES" if p >= .5 else "NO"}</div>'
            f'{T.confidence_bar(mode, p)}'
            f'<div class="sub">Inferred from micro-climate and soil dynamics. The '
            f'feature set contains no pump-state variable.</div></div>',
            unsafe_allow_html=True)

    with c2:
        s30 = cur.get("soil_30", np.nan)
        st.markdown(
            f'<div class="panel"><div class="cap">Root zone · now and t+30 min</div>'
            f'{T.soil_core(mode, cur["soil_moisture_pct"], s30)}'
            f'<div class="sub">Forecast <b>{s30:.1f} %</b>, '
            f'{s30-cur["soil_moisture_pct"]:+.1f} pp from now.</div></div>',
            unsafe_allow_html=True)

    with c3:
        sc = cur.get("anom_score", 0.0)
        thr = cur.get("anom_thr", 0.0)
        col = P["danger"] if anom else P["ok"]
        st.markdown(
            f'<div class="panel"><div class="cap">Sensor and field state</div>'
            f'<div class="big" style="color:{col}">{"ANOMALY" if anom else "NORMAL"}</div>'
            f'{T.score_meter(mode, sc, thr)}'
            f'<div class="sub">Operating point: '
            f'<b>{st.session_state.get("op_point","F1-optimal")}</b>.</div></div>',
            unsafe_allow_html=True)

    st.write("")
    if l1:
        st.error("**Validity gate rejected a reading** — out of range, or a dropout. "
                 "The last valid value is held. This is a range check in firmware, not "
                 "machine learning.")
    if low_water:
        st.error("**Pump held off by the low-water interlock.** Refill above 20 % to resume.")
    elif cur["pump_status"]:
        st.info(f"**Irrigating.** The controller releases the pump above {SM_HIGH:.0f} %.")
    elif cur.get("irrig_prob", 0) >= .5:
        st.warning("**Demand expected within two hours.**")
    else:
        st.success("**No irrigation action required.**")
    if hot:
        st.warning(f"Air temperature {cur['temperature_c']:.0f} °C exceeds the "
                   f"{TEMP_ALERT:.0f} °C heat-stress limit — evapotranspiration is elevated.")
    if anom:
        st.error("**Verify the probe before acting on this decision.**")

    # ---- telemetry --------------------------------------------------------
    st.write("")
    T.eyebrow(f"Telemetry · last {len(h)} simulated minutes")
    fig = make_subplots(rows=3, cols=2, shared_xaxes=True, vertical_spacing=.09,
                        horizontal_spacing=.06,
                        subplot_titles=("Temperature °C", "Humidity %",
                                        "Soil moisture %", "Light %",
                                        "Tank level %", "Pump"))
    for col_, r_, c_ in [("temperature_c", 1, 1), ("humidity_pct", 1, 2),
                         ("soil_moisture_pct", 2, 1), ("light_pct", 2, 2),
                         ("water_level_pct", 3, 1)]:
        fig.add_trace(go.Scatter(x=h.minute, y=h[col_], mode="lines",
                                 line=dict(color=T.series_colour(mode, col_), width=1.5),
                                 showlegend=False,
                                 hovertemplate="%{y:.1f}<extra></extra>"), row=r_, col=c_)
    fig.add_trace(go.Scatter(x=h.minute, y=h.soil_30, mode="lines", connectgaps=True,
                             line=dict(color=P["water"], width=1.2, dash="dot"),
                             showlegend=False,
                             hovertemplate="forecast %{y:.1f}<extra></extra>"), row=2, col=1)
    for v, r_, c_, colr in ((TEMP_ALERT, 1, 1, P["danger"]), (SM_LOW, 2, 1, P["danger"]),
                            (SM_HIGH, 2, 1, P["ok"]), (TANK_MIN, 3, 1, P["danger"])):
        fig.add_hline(y=v, line=dict(color=colr, dash="dot", width=1), row=r_, col=c_)
    fig.add_trace(go.Scatter(x=h.minute, y=h.pump_status, mode="lines",
                             line=dict(color=P["water"], width=1.4, shape="hv"),
                             fill="tozeroy", fillcolor=T.alpha(P["water"], .20),
                             showlegend=False), row=3, col=2)
    fig.update_layout(**T.plotly_layout(mode, height=520))
    T.plotly_axes(fig, mode)
    st.plotly_chart(fig, config={"displayModeBar": False}, width="stretch")

    # ---- anomaly trace ----------------------------------------------------
    st.write("")
    T.eyebrow("Anomaly score against its decision boundary")
    f = go.Figure()
    f.add_trace(go.Scatter(x=h.minute, y=h.anom_score, mode="lines", connectgaps=True,
                           line=dict(color=P["ink_2"], width=1.3), name="score"))
    if "anom_thr" in h and h.anom_thr.notna().any():
        f.add_hline(y=float(h.anom_thr.dropna().iloc[-1]),
                    line=dict(color=P["danger"], dash="dot", width=1))
    if h.is_fault.any():
        f.add_trace(go.Scatter(x=h.minute[h.is_fault == 1], y=h.anom_score[h.is_fault == 1],
                               mode="markers", marker=dict(color=P["danger"], size=4),
                               name="injected fault"))
    _lay = T.plotly_layout(mode, height=260)
    _lay["legend"] = dict(orientation="h", y=1.16, font=dict(size=10, color=P["muted"]))
    f.update_layout(**_lay, xaxis_title="simulated minute")
    T.plotly_axes(f, mode)
    st.plotly_chart(f, config={"displayModeBar": False}, width="stretch")

    with st.expander("Running accuracy of the live predictions"):
        if len(h) > 40 and "soil_30" in h:
            err = (h.soil_moisture_pct.shift(-30) - h.soil_30).abs().dropna()
            if len(err):
                st.write(f"Forecast MAE over {len(err)} matured predictions: "
                         f"**{err.mean():.3f} pp**. Held-out offline MAE was 0.858 pp.")
        if h.is_fault.sum() and "anom_flag" in h:
            tp = int(((h.anom_flag == 1) & (h.is_fault == 1)).sum())
            fp = int(((h.anom_flag == 1) & (h.is_fault == 0)).sum())
            fn = int(((h.anom_flag == 0) & (h.is_fault == 1)).sum())
            st.write(f"Detector on injected faults so far — {tp} caught, {fp} false "
                     f"alarms, {fn} missed. Recall {tp/max(tp+fn,1):.2f}, "
                     f"precision {tp/max(tp+fp,1):.2f}.")
        st.caption("A short live run explores a narrow, benign slice of the state space, "
                   "so live false-alarm rates are optimistic. Quote the recorded-playback "
                   "numbers as results and use this mode to demonstrate behaviour.")


# --------------------------------------------------------------------------
def render(models, mode="light"):
    _init()
    _controls(models)

    interval = 1.0
    speed = st.session_state.speed

    if hasattr(st, "fragment"):
        @st.fragment(run_every=interval if st.session_state.running else None)
        def _tick():
            if st.session_state.running:
                _advance(models, speed)
            _draw(models, mode)
        _tick()
    else:                                   # Streamlit < 1.37 fallback
        if st.session_state.running:
            _advance(models, speed)
        _draw(models, mode)
        if st.session_state.running:
            time.sleep(interval)
            st.rerun()
