r"""
Smart Agriculture — control centre
==================================
    streamlit run dashboard/app.py

Two modes, chosen in the sidebar:

  Recorded playback   replays the held-out test period. Every number on screen is
                      a model output on data it never saw in training, so this is
                      the mode to quote results from.

  Live simulation     integrates the field forward in real time and re-scores the
                      models each tick. Use it to demonstrate behaviour.

Runs entirely offline against the pipeline artefacts in data/, models/ and
reports/.
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import joblib
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme as T

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA, MOD, REP, FIG = (os.path.join(ROOT, d) for d in ("data", "models", "reports", "figures"))

SM_LOW, SM_HIGH, TANK_MIN, TEMP_ALERT = 35.0, 60.0, 20.0, 35.0
TRAIN_DAYS = 15


def data_path(name):
    """Prefer the gzipped copy when it exists. pandas reads .csv.gz natively, so
    the deployed repo carries 6 MB instead of 25 MB with no code change."""
    gz = os.path.join(DATA, name + ".gz")
    return gz if os.path.exists(gz) else os.path.join(DATA, name)

st.set_page_config(page_title="Smart Agriculture · Control Centre",
                   page_icon="🌾", layout="wide",
                   initial_sidebar_state="expanded")


# ---------------------------------------------------------------- loading ---
@st.cache_data
def load_data():
    return pd.read_csv(data_path("processed_dataset.csv"), parse_dates=["timestamp"])


@st.cache_resource
def load_models():
    out = {}
    for key, fn in (("m1", "m1_rf_classifier.joblib"),
                    ("m2", "m2_rf_regressor.joblib"),
                    ("m3", "m3_isolation_forest.joblib")):
        p = os.path.join(MOD, fn)
        out[key] = joblib.load(p) if os.path.exists(p) else None
    return out


@st.cache_data
def load_metrics():
    p = os.path.join(REP, "model_metrics.json")
    return json.load(open(p)) if os.path.exists(p) else {}


df = load_data()
models = load_models()
metrics = load_metrics()

# ------------------------------------------------------------- appearance ---
# The appearance switch sits top-right of the page rather than in the sidebar:
# it changes how everything looks, so it belongs with the page, not with the
# controls that change what the page is showing.
head_left, head_right = st.columns([3, 1.15], vertical_alignment="center")
with head_right:
    if hasattr(st, "segmented_control"):
        choice = st.segmented_control("Appearance", ["System", "Light", "Dark"],
                                      default="System", key="appearance",
                                      label_visibility="collapsed")
    else:
        choice = st.radio("Appearance", ["System", "Light", "Dark"],
                          horizontal=True, label_visibility="collapsed")

MODE = T.resolve_mode({"System": "Match system"}.get(choice, choice) or "Match system")
T.inject_css(MODE)
P = T.palette(MODE)

with head_left:
    st.markdown(T.tidy(
        '<div class="idcard">'
        '<div class="nm">Tanmay Gautam</div>'
        '<div class="rule"></div>'
        '<div class="meta">USN <b>2548559</b><br>Class <b>4MSAIM</b></div>'
        '</div>'), unsafe_allow_html=True)

st.sidebar.markdown("# Control centre")
st.sidebar.caption("field-node-01 · six channels · 1 min cadence")
st.sidebar.divider()
SOURCE = st.sidebar.radio(
    "Data source", ["Recorded playback", "Live simulation"],
    captions=["Held-out test period — quote results from here",
              "Field runs forward, one sim-minute per tick"])

# ------------------------------------------------------------- live mode ----
if SOURCE == "Live simulation":
    import live_panel
    with head_left:
        st.markdown("# Smart agriculture, live")
    st.markdown('<div class="clockline">The field is integrated forward in real time. '
                'Lags and rolling windows come from a genuine buffer, so the models '
                'see the feature definitions they were trained on.</div>',
                unsafe_allow_html=True)
    st.write("")
    live_panel.render(models, MODE)
    st.stop()


# ==========================================================================
#  RECORDED PLAYBACK
# ==========================================================================
test = df[df.day_of_campaign >= TRAIN_DAYS].reset_index(drop=True)

_pp = data_path("test_predictions.csv")
if os.path.exists(_pp):
    _pf = pd.read_csv(_pp, parse_dates=["timestamp"])[["timestamp", "pred_anomaly"]]
    test = test.merge(_pf, on="timestamp", how="left")
    test["pred_anomaly"] = test["pred_anomaly"].fillna(0).astype(int)
else:
    test["pred_anomaly"] = 0

SCENARIOS = {
    "Free playback": None,
    "S1 · Normal conditions": "normal",
    "S2 · Dry soil, irrigation on": "dry",
    "S3 · Recovered, irrigation off": "wet",
    "S4 · Low tank, pump inhibited": "lowtank",
    "S5 · High temperature": "hot",
    "S6 · Sensor drift detected": "anomaly",
}


def find_scenario(kind):
    d = test
    if kind == "normal":
        m = ((d.is_anomaly == 0) & (d.pred_anomaly == 0) & (d.pump_status == 0)
             & (d.temperature_c < 30) & d.soil_moisture_pct.between(42, 58)
             & (d.water_level_pct > 45) & (d.light_pct > 5))
    elif kind == "dry":
        m = (d.pump_status.diff() == 1).rolling(6, min_periods=1).max().astype(bool) \
            & (d.pump_status == 1)
    elif kind == "wet":
        m = (d.pump_status.diff() == -1).rolling(6, min_periods=1).max().astype(bool) \
            & (d.soil_moisture_pct > SM_HIGH)
    elif kind == "lowtank":
        m = d.water_level_pct <= TANK_MIN
        if not m.any():
            m = d.water_level_pct <= d.water_level_pct.quantile(.01)
    elif kind == "hot":
        m = (d.temperature_c >= TEMP_ALERT) & (d.is_anomaly == 0) & (d.pred_anomaly == 0)
    else:
        m = (d.anomaly_type == "drift:soil_moisture_pct") & (d.pred_anomaly == 1)
        if m.sum() < 5:
            m = (d.is_anomaly == 1) & (d.pred_anomaly == 1)
    idx = np.where(m.to_numpy())[0]
    return int(idx[len(idx) // 2]) if len(idx) else len(d) // 2


st.sidebar.divider()
scenario = st.sidebar.selectbox("Demonstration scenario", list(SCENARIOS))
default_i = find_scenario(SCENARIOS[scenario]) if SCENARIOS[scenario] else len(test) - 1
cursor = st.sidebar.slider("Playback cursor (minute)", 0, len(test) - 1, default_i)
window_h = st.sidebar.select_slider("History window (hours)",
                                    [3, 6, 12, 24, 48, 96], value=24)
st.sidebar.divider()
st.sidebar.caption(f"Training days 0–{TRAIN_DAYS-1} · test days {TRAIN_DAYS}–20 "
                   f"(shown here). The models never saw any of this period.")

row = test.iloc[cursor]
hist = test.iloc[max(0, cursor - window_h * 60): cursor + 1]


# ------------------------------------------------------------- inference ----
def infer(single_row):
    out = {}
    if models["m1"]:
        X = single_row[models["m1"]["features"]].to_frame().T.astype(float)
        out["irrig_prob"] = float(models["m1"]["model"].predict_proba(X)[0, 1])
    if models["m2"]:
        X = single_row[models["m2"]["features"]].to_frame().T.astype(float)
        out["soil_30"] = float(models["m2"]["model"].predict(X)[0])
    if models["m3"]:
        X = single_row[models["m3"]["features"]].to_frame().T.astype(float)
        X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["anom_score"] = float(-models["m3"]["model"].decision_function(X)[0])
        out["anom_pred"] = int(out["anom_score"] > 0.0)
    return out


pred = infer(row)
low_water = row.water_level_pct <= TANK_MIN
hot = row.temperature_c >= TEMP_ALERT
anom = bool(pred.get("anom_pred", 0))

# ------------------------------------------------------------------ header --
with head_left:
    st.markdown("# Smart agriculture control centre")
st.markdown(f'<div class="clockline">Reading <b>{row.timestamp}</b> · '
            f'scenario <b>{scenario}</b> · cursor <b>{cursor}</b> of {len(test)-1}'
            f'</div>', unsafe_allow_html=True)
st.write("")

T.status_strip([
    ("Irrigating" if row.pump_status else "Pump idle", "water" if row.pump_status else "ok"),
    ("Low water — pump inhibited" if low_water else "Tank healthy",
     "danger" if low_water else "ok"),
    ("Heat stress" if hot else "Temperature normal", "warn" if hot else "ok"),
    ("Anomaly detected" if anom else "Sensors nominal", "danger" if anom else "ok"),
])

# ------------------------------------------------------------- readouts -----
prev = test.iloc[max(0, cursor - 30)]
T.readout_row(MODE, [
    dict(label="Temperature", value=f"{row.temperature_c:.0f}", unit="°C",
         delta=row.temperature_c - prev.temperature_c, note="30 min", colour="danger"),
    dict(label="Humidity", value=f"{row.humidity_pct:.0f}", unit="%",
         delta=row.humidity_pct - prev.humidity_pct, note="30 min", colour="water"),
    dict(label="Soil moisture", value=f"{row.soil_moisture_pct:.1f}", unit="%",
         delta=row.soil_moisture_pct - prev.soil_moisture_pct, note="30 min", colour="soil"),
    dict(label="Light", value=f"{row.light_pct:.0f}", unit="%",
         delta=row.light_pct - prev.light_pct, note="30 min", colour="warn"),
    dict(label="Tank level", value=f"{row.water_level_pct:.0f}", unit="%",
         delta=row.water_level_pct - prev.water_level_pct, note="30 min", colour="ok"),
    dict(label="Pump", value="ON" if row.pump_status else "OFF", unit="",
         delta=f"{100*hist.pump_status.mean():.0f}% duty",
         note=f"{window_h} h", colour="water" if row.pump_status else "line"),
])
st.write("")

# --------------------------------------------------------- decision panel ---
T.eyebrow("Decision support")
c1, c2, c3 = st.columns([1, 1.05, 1.15])

with c1:
    p = pred.get("irrig_prob", 0.0)
    verdict = "YES" if p >= .5 else "NO"
    col = P["water"] if p >= .5 else P["muted"]
    st.markdown(
        f'<div class="panel"><div class="cap">Irrigation demand · next 120 min</div>'
        f'<div class="big" style="color:{col}">{verdict}</div>'
        f'{T.confidence_bar(MODE, p)}'
        f'<div class="sub">Will the root zone cross its 35 % depletion line, '
        f'assuming no irrigation and given water is available?</div></div>',
        unsafe_allow_html=True)

with c2:
    s30 = pred.get("soil_30", np.nan)
    delta = s30 - row.soil_moisture_pct
    st.markdown(
        f'<div class="panel"><div class="cap">Root zone · now and t+30 min</div>'
        f'{T.soil_core(MODE, row.soil_moisture_pct, s30)}'
        f'<div class="sub">Forecast <b>{s30:.1f} %</b>, {delta:+.1f} pp from now. '
        f'Crosses the start set-point: {"yes" if s30 < SM_LOW else "no"}.</div></div>',
        unsafe_allow_html=True)

with c3:
    sc = pred.get("anom_score", 0.0)
    col = P["danger"] if anom else P["ok"]
    truth = (f'<div class="sub">Labelled fault in this window: '
             f'<b>{row.anomaly_type}</b>.</div>') if row.is_anomaly == 1 else ""
    st.markdown(
        f'<div class="panel"><div class="cap">Sensor and field state</div>'
        f'<div class="big" style="color:{col}">{"ANOMALY" if anom else "NORMAL"}</div>'
        f'{T.score_meter(MODE, sc, 0.0)}'
        f'<div class="sub">Isolation Forest scores how far this reading sits from '
        f'what the physics and the last six hours allow.</div>{truth}</div>',
        unsafe_allow_html=True)

st.write("")
if low_water:
    st.error("**Pump held off by the low-water interlock.** Refill the tank; the "
             "controller resumes automatically above 20 %.")
elif row.pump_status:
    st.info(f"**Irrigating.** The controller releases the pump above {SM_HIGH:.0f} % "
            f"soil moisture, not at the 35 % start point — that dead band is what "
            f"stops the relay chattering.")
elif pred.get("irrig_prob", 0) >= .5:
    st.warning("**Demand expected within two hours.** Pre-position the valve or batch "
               "this plot with the next scheduled cycle.")
else:
    st.success("**No irrigation action required.**")

if hot:
    st.warning(f"Air temperature {row.temperature_c:.0f} °C is above the "
               f"{TEMP_ALERT:.0f} °C heat-stress limit, so evapotranspiration is "
               f"elevated. Heat alone does not trigger irrigation — soil water does.")
if anom:
    st.error("**Verify the probe before acting on this decision.** When the input is "
             "corrupted the forecast degrades silently, returning a confident wrong "
             "number rather than an error.")

# ------------------------------------------------------------- telemetry ----
st.write("")
T.eyebrow(f"Telemetry · last {window_h} hours")

fig = make_subplots(rows=3, cols=2, shared_xaxes=True, vertical_spacing=.09,
                    horizontal_spacing=.06,
                    subplot_titles=("Temperature °C", "Humidity %",
                                    "Soil moisture %", "Light %",
                                    "Tank level %", "Pump"))
spec = [("temperature_c", 1, 1), ("humidity_pct", 1, 2), ("soil_moisture_pct", 2, 1),
        ("light_pct", 2, 2), ("water_level_pct", 3, 1)]
for col, r_, c_ in spec:
    fig.add_trace(go.Scatter(x=hist.timestamp, y=hist[col], mode="lines",
                             line=dict(color=T.series_colour(MODE, col), width=1.5),
                             name=col, showlegend=False,
                             hovertemplate="%{y:.1f}<extra></extra>"),
                  row=r_, col=c_)
for v, r_, c_, colr in ((TEMP_ALERT, 1, 1, P["danger"]), (SM_LOW, 2, 1, P["danger"]),
                        (SM_HIGH, 2, 1, P["ok"]), (TANK_MIN, 3, 1, P["danger"])):
    fig.add_hline(y=v, line=dict(color=colr, dash="dot", width=1), row=r_, col=c_)
fig.add_trace(go.Scatter(x=hist.timestamp, y=hist.pump_status, mode="lines",
                         line=dict(color=P["water"], width=1.4, shape="hv"),
                         fill="tozeroy", fillcolor=T.alpha(P["water"], .20),
                         showlegend=False), row=3, col=2)
fig.update_layout(**T.plotly_layout(MODE, height=520))
T.plotly_axes(fig, MODE)
st.plotly_chart(fig, config={"displayModeBar": False}, width="stretch")

# ------------------------------------------------------------------ tabs ----
st.write("")
tab1, tab2, tab3, tab4 = st.tabs(
    ["Forecast vs actual", "What the models use", "Correlations", "Anomaly log"])

with tab1:
    if os.path.exists(_pp):
        tp = pd.read_csv(_pp, parse_dates=["timestamp"])
        w = tp[(tp.timestamp >= hist.timestamp.min()) & (tp.timestamp <= hist.timestamp.max())]
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=w.timestamp, y=w.soil_moisture_future_30,
                                name="Actual at t+30",
                                line=dict(color=P["ink_2"], width=1.7)))
        f2.add_trace(go.Scatter(x=w.timestamp, y=w.pred_soil_future_30,
                                name="Forecast", line=dict(color=P["soil"], width=1.7)))
        f2.add_hline(y=SM_LOW, line=dict(color=P["danger"], dash="dot", width=1))
        f2.update_layout(**T.plotly_layout(MODE, height=330),
                         yaxis_title="Soil moisture %")
        T.plotly_axes(f2, MODE)
        st.plotly_chart(f2, config={"displayModeBar": False}, width="stretch")
        err = (w.soil_moisture_future_30 - w.pred_soil_future_30).abs()
        st.caption(f"Window MAE {err.mean():.3f} pp · worst {err.max():.3f} pp · "
                   f"{100*(err<=1).mean():.1f} % of minutes within 1 pp. "
                   f"Held-out MAE across the whole test period was 0.858 pp.")

with tab2:
    cols = st.columns(2)
    if metrics.get("M1_classifier", {}).get("top_permutation_importance"):
        s = pd.Series(metrics["M1_classifier"]["top_permutation_importance"]).head(12)[::-1]
        f = go.Figure(go.Bar(x=s.values, y=s.index, orientation="h",
                             marker_color=P["water"]))
        f.update_layout(**T.plotly_layout(MODE, height=380),
                        title=dict(text="Demand classifier · permutation importance",
                                   font=dict(size=12, color=P["ink_2"])))
        T.plotly_axes(f, MODE)
        cols[0].plotly_chart(f, config={"displayModeBar": False}, width="stretch")
    if metrics.get("M2_regressor", {}).get("top_gini_importance"):
        s = pd.Series(metrics["M2_regressor"]["top_gini_importance"]).head(12)[::-1]
        f = go.Figure(go.Bar(x=s.values, y=s.index, orientation="h",
                             marker_color=P["soil"]))
        f.update_layout(**T.plotly_layout(MODE, height=380),
                        title=dict(text="Soil forecaster · impurity importance",
                                   font=dict(size=12, color=P["ink_2"])))
        T.plotly_axes(f, MODE)
        cols[1].plotly_chart(f, config={"displayModeBar": False}, width="stretch")
    st.caption("Permutation importance is measured on the test set, so it reflects "
               "predictive contribution on unseen data. Impurity importance is measured "
               "during training and favours high-cardinality continuous features — "
               "where the two disagree, the disagreement is itself diagnostic.")

with tab3:
    SENS = ["temperature_c", "humidity_pct", "soil_moisture_pct",
            "light_pct", "water_level_pct", "vpd_hpa", "et_proxy"]
    corr = df[SENS].corr().round(3)
    f = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.columns,
                             colorscale=[[0, P["water"]], [.5, P["surface_2"]],
                                         [1, P["soil"]]],
                             zmid=0, text=corr.values, texttemplate="%{text}",
                             textfont=dict(size=10, family="IBM Plex Mono, monospace"),
                             showscale=False))
    f.update_layout(**T.plotly_layout(MODE, height=430))
    T.plotly_axes(f, MODE)
    st.plotly_chart(f, config={"displayModeBar": False}, width="stretch")
    st.caption("Temperature and humidity sit at −0.93 because humidity was derived "
               "through the Magnus saturation curve, not specified directly. "
               "Spearman exceeds Pearson for soil moisture, which says the relationship "
               "is monotone but non-linear — the argument for tree models over linear ones.")

with tab4:
    if os.path.exists(_pp):
        tp = pd.read_csv(_pp, parse_dates=["timestamp"])
        flagged = tp[tp.pred_anomaly == 1].copy()
        flagged["verdict"] = np.where(flagged.is_anomaly == 1,
                                      "caught · " + flagged.anomaly_type,
                                      "false alarm")
        st.caption(f"{len(flagged):,} readings flagged of {len(tp):,} "
                   f"({100*len(flagged)/len(tp):.1f} %). Sorted by score.")
        st.dataframe(flagged[["timestamp", "soil_moisture_pct", "water_level_pct",
                              "temperature_c", "anomaly_score", "verdict"]]
                     .sort_values("anomaly_score", ascending=False).head(200),
                     hide_index=True, width="stretch", height=420)

# ----------------------------------------------------------- model card -----
st.write("")
with st.expander("Model performance on the held-out test period"):
    if metrics:
        m1 = metrics.get("M1_classifier", {})
        m2 = metrics.get("M2_regressor", {})
        m3 = metrics.get("M3_isolation_forest", {})
        a, b, c = st.columns(3)
        a.markdown(
            f'<div class="panel"><div class="cap">M1 · demand classifier</div>'
            f'<div class="big">{m1.get("f1",0):.3f} F1</div>'
            f'<div class="sub">Accuracy {m1.get("accuracy",0):.3f} · '
            f'precision {m1.get("precision",0):.3f} · recall {m1.get("recall",0):.3f} · '
            f'ROC-AUC {m1.get("roc_auc",0):.3f}.<br>Reactive threshold rule: F1 '
            f'{m1.get("baseline_current_threshold_rule",{}).get("f1",0):.3f}.</div></div>',
            unsafe_allow_html=True)
        b.markdown(
            f'<div class="panel"><div class="cap">M2 · soil forecaster</div>'
            f'<div class="big">{m2.get("r2",0):.3f} R²</div>'
            f'<div class="sub">MAE {m2.get("mae",0):.3f} pp · RMSE {m2.get("rmse",0):.3f} pp.'
            f'<br>Persistence baseline RMSE '
            f'{m2.get("baseline_persistence",{}).get("rmse",0):.3f} pp, so the skill score '
            f'is {m2.get("skill_score_vs_persistence",0):.3f}.</div></div>',
            unsafe_allow_html=True)
        c.markdown(
            f'<div class="panel"><div class="cap">M3 · anomaly detector</div>'
            f'<div class="big">{m3.get("roc_auc",0):.3f} AUC</div>'
            f'<div class="sub">Precision {m3.get("precision",0):.3f} · '
            f'recall {m3.get("recall",0):.3f} · F1 {m3.get("f1",0):.3f}.'
            f'<br>Rolling z-score baseline: precision 0.268, recall 0.088. '
            f'Dropouts are handled by the validity gate, not by this model.</div></div>',
            unsafe_allow_html=True)
    else:
        st.info("Run `python python/03_train_models.py` to populate the metrics.")

# ---------------------------------------------------------- hardware -------
st.write("")
T.eyebrow("Hardware · the field node")

hw_a, hw_b = st.tabs(["Interactive node", "Wokwi circuit"])

with hw_a:
    st.caption("The firmware's control law, alert state machine and display logic, "
               "running live. Drive the sensors on the left and watch the outputs. "
               "Hysteresis, the dwell timer and the low-water interlock are all "
               "behaviours over time, which a screenshot cannot show.")
    import node_bench
    node_bench.render(MODE)

with hw_b:
    _circuit = os.path.join(ROOT, "assets", "wokwi_circuit.png")
    cc1, cc2 = st.columns([1.55, 1])
    with cc1:
        if os.path.exists(_circuit):
            st.image(_circuit,
                     caption="ESP32 node in Wokwi — DHT22, soil probe, LDR, HC-SR04, "
                             "relay, buzzer, status LEDs and a 16x2 I2C display.",
                     width="stretch")
        else:
            st.info("Drop a screenshot at assets/wokwi_circuit.png to show it here.")
    with cc2:
        st.markdown(
            '<div class="panel"><div class="cap">Channel map</div>'
            '<div class="sub">'
            '<b>GPIO 4</b> · DHT22 temperature and humidity<br>'
            '<b>GPIO 34</b> · soil moisture (ADC1)<br>'
            '<b>GPIO 35</b> · light intensity (ADC1)<br>'
            '<b>GPIO 12 / 14</b> · HC-SR04 trigger and echo<br>'
            '<b>GPIO 26</b> · relay, irrigation pump<br>'
            '<b>GPIO 25</b> · buzzer<br>'
            '<b>GPIO 27 / 33 / 32</b> · OK, pump, alert LEDs<br>'
            '<b>GPIO 21 / 22</b> · I2C display'
            '</div></div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="panel" style="margin-top:10px"><div class="cap">Why Wokwi</div>'
            '<div class="sub">Both analogue sensors sit on ADC1 because ADC2 is claimed '
            'by the radio once WiFi associates. Wokwi simulates the full network stack, '
            'so this node genuinely posts to the ThingSpeak channel — Tinkercad has no '
            'network stack at all. The hysteresis control law running here is identical '
            'to the Arduino Uno build.</div></div>', unsafe_allow_html=True)
