r"""
node_bench.py
=============
An interactive emulation of the FIRMWARE, drawn as the node.

Be precise about what this is when you present it: it is not a circuit
simulator. It does not model voltages, ADC counts or bus timing — Wokwi does
that, and the screenshot beside it is the evidence of the real circuit. What
this reproduces is the part that matters for the project's argument: the exact
control law, alert state machine and display logic from
`smart_agri_esp32_thingspeak.ino`, running live so an examiner can drive the
inputs and watch the outputs respond.

The value over a screenshot is that hysteresis, the dwell timer and the
low-water interlock are all behaviours over time. A still image cannot show any
of them; three sliders and a board that lights up can.

Every constant below is copied from the firmware. If you change one there,
change it here, or the demonstration stops being evidence.
"""

import time
import streamlit as st
import theme as T

# ---- must match the firmware -------------------------------------------
SM_LOW, SM_HIGH = 35.0, 60.0
TANK_MIN, TEMP_ALERT = 20.0, 35.0
MIN_PUMP_S = 10.0                    # MIN_PUMP_MS in the sketch
TANK_HEIGHT_CM, SENSOR_GAP_CM = 40.0, 4.0

ALERTS = {
    0: ("NORMAL", "Status: NORMAL ", None),
    1: ("LOW WATER", "! LOW WATER LVL", 900),
    2: ("HIGH TEMP", "! HIGH TEMP    ", 1500),
    3: ("LOW WATER + HEAT", "! LOW H2O+HEAT ", 2000),
    4: ("SENSOR FAULT", "! SENSOR FAULT ", 400),
}


# --------------------------------------------------------------------------
def _init():
    st.session_state.setdefault("bench_pump", False)
    st.session_state.setdefault("bench_since", time.time() - MIN_PUMP_S)


def level_from_distance(cm, echo_ok):
    """HC-SR04 measures the air gap, so level is the complement. No echo = -1."""
    if not echo_ok:
        return -1.0
    return max(0.0, min(100.0, (1.0 - (cm - SENSOR_GAP_CM) / TANK_HEIGHT_CM) * 100.0))


def control(soil, tank, temp):
    """The firmware's updateControl(), verbatim."""
    prev = st.session_state.bench_pump
    low_water = (tank <= TANK_MIN) or (tank < 0)
    dwell_left = max(0.0, MIN_PUMP_S - (time.time() - st.session_state.bench_since))
    dwell_ok = dwell_left <= 0

    pump = prev
    if low_water:
        pump = False                                   # interlock, evaluated first
    elif not prev and soil < SM_LOW and dwell_ok:
        pump = True
    elif prev and soil > SM_HIGH and dwell_ok:
        pump = False

    if pump != prev:
        st.session_state.bench_since = time.time()
        dwell_left = MIN_PUMP_S
    st.session_state.bench_pump = pump

    hot = temp >= TEMP_ALERT
    bad = tank < 0
    if bad:                     alert = 4
    elif low_water and hot:     alert = 3
    elif low_water:             alert = 1
    elif hot:                   alert = 2
    else:                       alert = 0

    return pump, alert, dwell_left, low_water


# --------------------------------------------------------------------------
def _board_svg(mode, t, h, soil, light, tank, dist, pump, alert, echo_ok):
    """The node, drawn as an instrument rather than a photograph."""
    p = T.palette(mode)
    body = p["surface_2"]
    edge = p["line"]
    txt = p["ink"]
    dim = p["muted"]
    mono = "IBM Plex Mono, monospace"

    on_g = alert == 0
    on_y = pump
    on_r = alert != 0
    buzz = ALERTS[alert][2]

    def led(cx, cy, colour, on, label):
        glow = (f'<circle cx="{cx}" cy="{cy}" r="17" fill="{colour}" opacity=".28"/>'
                f'<circle cx="{cx}" cy="{cy}" r="26" fill="{colour}" opacity=".10"/>') if on else ""
        return (f'{glow}'
                f'<circle cx="{cx}" cy="{cy}" r="9" fill="{colour if on else p["line"]}" '
                f'stroke="{edge}" stroke-width="1"/>'
                f'<text x="{cx}" y="{cy+26}" font-size="8" fill="{dim}" text-anchor="middle" '
                f'font-family="{mono}" letter-spacing=".08em">{label}</text>')

    def wire(pts, colour, active=False, flow=False):
        cls = ' class="flow"' if (flow and active) else ""
        return (f'<polyline points="{pts}" fill="none" '
                f'stroke="{colour if active else edge}" '
                f'stroke-width="{2 if active else 1.3}" '
                f'opacity="{1 if active else .55}"{cls}/>')

    def sensor(x, y, w, name, value, pin, colour):
        return f'''
      <rect x="{x}" y="{y}" width="{w}" height="42" rx="7" fill="{body}"
            stroke="{edge}" stroke-width="1"/>
      <text x="{x+10}" y="{y+16}" font-size="8.5" fill="{dim}" font-family="{mono}"
            letter-spacing=".1em">{name}</text>
      <text x="{x+10}" y="{y+33}" font-size="13" fill="{txt}" font-family="{mono}"
            font-weight="500">{value}</text>
      <text x="{x+w-8}" y="{y+33}" font-size="8" fill="{colour}" font-family="{mono}"
            text-anchor="end">{pin}</text>'''

    # LCD content, exactly what updateLcd() writes
    page = int(time.time() / 3) % 2
    if page == 0:
        l1 = f"T:{t:.1f}C H:{h:.0f}%"[:16]
        l2 = f"Soil:{soil:.0f}% {'PMP:ON' if pump else 'PMP:OF'}"[:16]
    else:
        l1 = f"Lgt:{light:.0f}% Tnk:{tank if tank >= 0 else 0:.0f}"[:16]
        l2 = ALERTS[alert][1][:16]

    relay_col = p["water"] if pump else p["line"]
    contact = "NO" if pump else "NC"

    return T.tidy(f'''
<svg viewBox="0 0 900 470" width="100%" role="img"
     aria-label="Field node: soil {soil:.0f} percent, tank {tank:.0f} percent, pump {"on" if pump else "off"}, alert {ALERTS[alert][0]}">
  <style>
    .flow {{ stroke-dasharray: 7 6; animation: dash 1s linear infinite; }}
    @keyframes dash {{ to {{ stroke-dashoffset: -13; }} }}
    @media (prefers-reduced-motion: reduce) {{ .flow {{ animation: none; }} }}
  </style>

  <!-- ============ inputs ============ -->
  <text x="24" y="26" font-size="8.5" fill="{dim}" font-family="{mono}"
        letter-spacing=".16em">SENSE</text>
  {sensor(24, 40, 190, "DHT22 · TEMPERATURE", f"{t:.1f} °C", "GPIO4", p["danger"])}
  {sensor(24, 96, 190, "DHT22 · HUMIDITY", f"{h:.0f} %", "GPIO4", p["water"])}
  {sensor(24, 152, 190, "SOIL PROBE", f"{soil:.1f} %", "GPIO34", p["soil"])}
  {sensor(24, 208, 190, "LDR · LIGHT", f"{light:.0f} %", "GPIO35", p["warn"])}
  {sensor(24, 264, 190, "HC-SR04 · DISTANCE",
          f"{dist:.1f} cm" if echo_ok else "no echo", "GPIO12/14",
          p["ok"] if echo_ok else p["danger"])}
  {sensor(24, 320, 190, "TANK LEVEL (DERIVED)",
          f"{tank:.0f} %" if tank >= 0 else "fault", "—",
          p["danger"] if (tank < 0 or tank <= TANK_MIN) else p["ok"])}

  <!-- ============ wires in ============ -->
  {wire("214,61 300,61 300,150 360,150", p["danger"], True)}
  {wire("214,117 290,117 290,168 360,168", p["water"], True)}
  {wire("214,173 280,173 280,186 360,186", p["soil"], True)}
  {wire("214,229 270,229 270,204 360,204", p["warn"], True)}
  {wire("214,285 260,285 260,222 360,222", p["ok"] if echo_ok else p["danger"], echo_ok)}

  <!-- ============ controller ============ -->
  <rect x="360" y="90" width="170" height="270" rx="12" fill="{body}"
        stroke="{edge}" stroke-width="1.4"/>
  <rect x="392" y="112" width="106" height="74" rx="6" fill="{p['bg']}"
        stroke="{edge}"/>
  <text x="445" y="156" font-size="15" fill="{txt}" text-anchor="middle"
        font-family="{mono}" font-weight="600" letter-spacing=".06em">ESP32</text>
  <text x="445" y="204" font-size="8" fill="{dim}" text-anchor="middle"
        font-family="{mono}" letter-spacing=".14em">HYSTERESIS CONTROL</text>

  <rect x="378" y="222" width="134" height="52" rx="6" fill="{p['bg']}" stroke="{edge}"/>
  <text x="388" y="238" font-size="8" fill="{dim}" font-family="{mono}">SET-POINTS</text>
  <text x="388" y="254" font-size="10" fill="{p['danger']}" font-family="{mono}">start &lt; {SM_LOW:.0f}%</text>
  <text x="388" y="268" font-size="10" fill="{p['ok']}" font-family="{mono}">stop &gt; {SM_HIGH:.0f}%</text>

  <text x="445" y="298" font-size="8.5" fill="{dim}" text-anchor="middle"
        font-family="{mono}">interlock: tank ≤ {TANK_MIN:.0f}%</text>
  <text x="445" y="313" font-size="8.5" fill="{p['warn']}" text-anchor="middle"
        font-family="{mono}">alert: temp ≥ {TEMP_ALERT:.0f}°C</text>
  <text x="445" y="340" font-size="9" fill="{p['danger'] if alert else p['ok']}"
        text-anchor="middle" font-family="{mono}" letter-spacing=".08em">
        {ALERTS[alert][0]}</text>

  <!-- ============ wires out ============ -->
  {wire("530,140 570,140 570,96 610,96", p["ok"], on_g)}
  {wire("530,152 560,152 560,96 676,96", p["warn"], on_y)}
  {wire("530,164 550,164 550,96 742,96", p["danger"], on_r)}
  {wire("530,200 570,200 570,196 610,196", p["water"], pump, flow=True)}
  {wire("530,240 566,240 566,286 610,286", p["danger"], buzz is not None)}
  {wire("530,300 556,300 556,360 610,360", p["water"], True)}

  <!-- ============ outputs ============ -->
  <text x="610" y="26" font-size="8.5" fill="{dim}" font-family="{mono}"
        letter-spacing=".16em">ACT</text>
  {led(610, 96, p["ok"], on_g, "OK")}
  {led(676, 96, p["warn"], on_y, "PUMP")}
  {led(742, 96, p["danger"], on_r, "ALERT")}

  <!-- relay + pump -->
  <rect x="610" y="168" width="260" height="58" rx="8" fill="{body}" stroke="{edge}"/>
  <text x="622" y="186" font-size="8.5" fill="{dim}" font-family="{mono}"
        letter-spacing=".1em">RELAY · GPIO26</text>
  <circle cx="632" cy="208" r="6" fill="{relay_col}"/>
  <text x="648" y="212" font-size="11" fill="{txt}" font-family="{mono}">
        COM–{contact}</text>
  <text x="742" y="212" font-size="11" fill="{p['water'] if pump else dim}"
        font-family="{mono}" font-weight="500">
        PUMP {"RUNNING" if pump else "IDLE"}</text>
  <text x="622" y="240" font-size="8" fill="{dim}" font-family="{mono}">
        module is active-LOW: IN low closes COM–NO</text>

  <!-- buzzer -->
  <rect x="610" y="262" width="260" height="46" rx="8" fill="{body}" stroke="{edge}"/>
  <text x="622" y="280" font-size="8.5" fill="{dim}" font-family="{mono}"
        letter-spacing=".1em">BUZZER · GPIO25</text>
  <text x="622" y="298" font-size="11" fill="{p['danger'] if buzz else dim}"
        font-family="{mono}">{f"{buzz} Hz" if buzz else "silent"}</text>
  {"".join(f'<circle cx="{800+i*18}" cy="286" r="{5+i*4}" fill="none" stroke="{p["danger"]}" stroke-width="1.4" opacity="{.7-i*.2}"/>' for i in range(3)) if buzz else ""}

  <!-- LCD -->
  <rect x="610" y="330" width="260" height="86" rx="8" fill="{body}" stroke="{edge}"/>
  <text x="622" y="348" font-size="8.5" fill="{dim}" font-family="{mono}"
        letter-spacing=".1em">LCD1602 · I²C GPIO21/22 · page {page+1}/2</text>
  <rect x="622" y="356" width="236" height="50" rx="4" fill="#1E3A1E" stroke="#0F1F0F"/>
  <text x="632" y="376" font-size="13" fill="#B8E986" font-family="{mono}"
        letter-spacing=".06em">{l1}</text>
  <text x="632" y="396" font-size="13" fill="#B8E986" font-family="{mono}"
        letter-spacing=".06em">{l2}</text>

  <text x="24" y="452" font-size="8" fill="{dim}" font-family="{mono}">
    Control law, alert codes and display strings are copied from the ESP32 firmware.
    This emulates the sketch, not the circuit — the Wokwi tab is the circuit.</text>
</svg>''')


# --------------------------------------------------------------------------
def render(mode):
    _init()
    P = T.palette(mode)

    left, right = st.columns([1, 2.35])

    with left:
        st.markdown('<div class="cap" style="margin-bottom:.4rem">Drive the inputs</div>',
                    unsafe_allow_html=True)
        soil = st.slider("Soil moisture %", 0.0, 100.0, 45.0, 0.5, key="bench_soil")
        dist = st.slider("HC-SR04 distance cm", 4.0, 46.0, 12.0, 0.5, key="bench_dist",
                         help="Air gap above the water. 4 cm is full, 44 cm is empty.")
        temp = st.slider("Temperature °C", 5.0, 50.0, 26.0, 0.5, key="bench_temp")
        hum = st.slider("Humidity %", 5.0, 100.0, 55.0, 1.0, key="bench_hum")
        light = st.slider("Light %", 0.0, 100.0, 60.0, 1.0, key="bench_light")
        echo_ok = not st.checkbox("Disconnect HC-SR04 echo wire", key="bench_echo",
                                  help="Simulates a broken sensor. Watch which way it fails.")

    tank = level_from_distance(dist, echo_ok)
    pump, alert, dwell_left, low_water = control(soil, tank, temp)

    with right:
        st.markdown(_board_svg(mode, temp, hum, soil, light, tank, dist,
                               pump, alert, echo_ok), unsafe_allow_html=True)

    # ---- what just happened, in words -----------------------------------
    a, b = st.columns([1.25, 1])
    with a:
        if alert == 4:
            st.error("**No echo from the tank sensor.** Treated as low water, so the pump "
                     "is inhibited — the system fails *closed*. A missed irrigation cycle "
                     "costs a day of growth; a dry-run pump costs the pump.")
        elif low_water:
            st.error(f"**Tank at {tank:.0f} %, at or below the {TANK_MIN:.0f} % interlock.** "
                     f"The pump is held off even though the soil may be dry. The interlock "
                     f"is the first branch in the control law, so nothing can bypass it.")
        elif pump and soil < SM_HIGH:
            st.info(f"**Irrigating.** Soil is {soil:.0f} %, above the {SM_LOW:.0f} % start "
                    f"point — and it keeps running. The pump only releases above "
                    f"{SM_HIGH:.0f} %. That gap is the hysteresis.")
        elif pump:
            st.info("**Irrigating.** Soil is above the stop set-point; the pump releases "
                    "on the next evaluation once the dwell timer clears.")
        elif soil < SM_LOW:
            st.warning(f"**Soil below the {SM_LOW:.0f} % start point** but the pump is off — "
                       f"either the dwell timer is still running or the tank is low.")
        else:
            st.success(f"**Idle.** Soil is {soil:.0f} %, inside the "
                       f"{SM_LOW:.0f}–{SM_HIGH:.0f} % dead band, so the controller holds "
                       f"its current state rather than switching.")
        if alert == 2:
            st.warning(f"Temperature {temp:.0f} °C is above the {TEMP_ALERT:.0f} °C limit. "
                       f"This raises an alert but does **not** start the pump — irrigating "
                       f"on air temperature rather than soil water is exactly the "
                       f"over-watering behaviour the project exists to prevent.")

    with b:
        bar = min(max(1 - dwell_left / MIN_PUMP_S, 0.0), 1.0)
        st.markdown(T.tidy(
            f'<div class="panel"><div class="cap">Anti-short-cycle dwell</div>'
            f'<div class="big" style="color:{P["muted"] if bar >= 1 else P["warn"]}">'
            f'{"ready" if bar >= 1 else f"{dwell_left:.1f} s"}</div>'
            f'{T.confidence_bar(mode, bar)}'
            f'<div class="sub">The relay cannot change state within {MIN_PUMP_S:.0f} s of '
            f'its last transition. Without it, a reading sitting exactly on a set-point '
            f'chatters the relay past its mechanical life.</div></div>'),
            unsafe_allow_html=True)

    with st.expander("Try these six, in order"):
        st.markdown(f"""
1. **Baseline** — soil 45 %, distance 12 cm. Everything green, pump idle.
2. **Start irrigation** — drag soil below {SM_LOW:.0f} %. Relay closes, yellow LED lights,
   the LCD flips to `PMP:ON`.
3. **Hysteresis** — drag soil slowly back up. It stays on through 40, 50, 55 % and only
   releases above {SM_HIGH:.0f} %. This is the single most important thing to point out:
   a plain comparator would have stopped at {SM_LOW:.0f} %.
4. **Interlock** — put soil below {SM_LOW:.0f} % again, then drag distance past 36 cm.
   The pump is forced off *despite* dry soil, and the buzzer drops to 900 Hz.
5. **Heat** — raise temperature past {TEMP_ALERT:.0f} °C with a healthy tank. Red LED and a
   1500 Hz chirp, but the pump is untouched.
6. **Fail closed** — tick the echo-wire checkbox. `pulseIn` times out, the reading becomes
   −1, and that is treated as low water rather than as a full tank.
""")
