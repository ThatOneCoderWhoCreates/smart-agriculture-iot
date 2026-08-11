r"""
theme.py
========
Visual system for the control centre.

Direction: SOIL HORIZON. The palette is read off a soil core - limestone paper
and umber over water-teal in daylight, wet loam and night field after dark. Both
modes are first-class; neither is a filter applied to the other.

Numerals are set in IBM Plex Mono with tabular figures. That is a functional
choice, not a stylistic one: in live mode the readouts update every second, and
proportional digits make the values jitter sideways as they change. Tabular mono
holds every digit in the same column so the eye can rest on the number.

Exports
-------
    palette(mode)        -> dict of tokens
    inject_css(mode)     -> writes the stylesheet into the page
    plotly_layout(mode)  -> kwargs for fig.update_layout()
    soil_core(...)       -> the signature gauge, as inline SVG
    score_meter(...)     -> anomaly score against its decision boundary
    status_strip(...)    -> the four condition chips
    readout(...)         -> one instrument readout tile
"""

import re

import streamlit as st

# --------------------------------------------------------------------------
# TOKENS
# --------------------------------------------------------------------------
LIGHT = {
    "mode": "light",
    "bg": "#FBFAF7",          # limestone paper
    "surface": "#FFFFFF",
    "surface_2": "#F3F1EB",
    "line": "#E2DED3",
    "line_soft": "#EFECE4",
    "ink": "#1F2420",
    "ink_2": "#4A5148",
    "muted": "#7C8479",
    "water": "#0E7C86",       # accent: irrigation water
    "soil": "#8A5A2B",        # accent: umber / root zone
    "ok": "#2E7D4F",
    "warn": "#B4740E",
    "danger": "#A93226",
    "ok_bg": "#E6F1EA",
    "warn_bg": "#FBF0DA",
    "danger_bg": "#F9E4E1",
    "water_bg": "#E1F0F1",
    "grid": "#ECE8DF",
    "shadow": "0 1px 2px rgba(31,36,32,.05), 0 8px 24px -16px rgba(31,36,32,.18)",
}

DARK = {
    "mode": "dark",
    "bg": "#101310",          # night field
    "surface": "#171B16",
    "surface_2": "#1E231D",
    "line": "#2C332B",
    "line_soft": "#232922",
    "ink": "#E9ECE4",
    "ink_2": "#C2C9BC",
    "muted": "#8B9488",
    "water": "#3FC2C9",
    "soil": "#C79055",
    "ok": "#63BE88",
    "warn": "#E0A63F",
    "danger": "#E4776A",
    "ok_bg": "#17281E",
    "warn_bg": "#2B2216",
    "danger_bg": "#2C1A18",
    "water_bg": "#12292B",
    "grid": "#242A23",
    "shadow": "0 1px 2px rgba(0,0,0,.4), 0 10px 30px -18px rgba(0,0,0,.8)",
}


def palette(mode):
    return DARK if mode == "dark" else LIGHT


def tidy(markup):
    """
    Collapse an HTML/SVG string onto one line before handing it to st.markdown.

    st.markdown runs the Markdown parser BEFORE it honours unsafe_allow_html, and
    Markdown turns any line indented by four or more spaces into a code block.
    A pretty-printed SVG therefore renders as visible source instead of a
    picture. Flattening the markup is the fix; blank lines have to go too,
    because they close the HTML block.
    """
    return re.sub(r"\s*\n\s*", " ", markup).strip()


def resolve_mode(choice):
    """'Match system' reads the theme Streamlit is actually rendering."""
    if choice == "Light":
        return "light"
    if choice == "Dark":
        return "dark"
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:                                     # older Streamlit
        return "light"


# --------------------------------------------------------------------------
# STYLESHEET
# --------------------------------------------------------------------------
def inject_css(mode):
    p = palette(mode)
    # Leading whitespace is stripped from every line: Markdown runs before
    # unsafe_allow_html, and a four-space indent inside the <style> block would
    # be parsed as a code fence, silently dropping part of the stylesheet.
    css = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap');

:root {{
  --bg:{p['bg']}; --surface:{p['surface']}; --surface2:{p['surface_2']};
  --line:{p['line']}; --lineSoft:{p['line_soft']};
  --ink:{p['ink']}; --ink2:{p['ink_2']}; --muted:{p['muted']};
  --water:{p['water']}; --soil:{p['soil']};
  --ok:{p['ok']}; --warn:{p['warn']}; --danger:{p['danger']};
  --okBg:{p['ok_bg']}; --warnBg:{p['warn_bg']}; --dangerBg:{p['danger_bg']};
  --waterBg:{p['water_bg']}; --shadow:{p['shadow']};
}}

/* ---- surfaces --------------------------------------------------------- */
[data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: var(--bg); }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebarContent"], section[data-testid="stSidebar"] {{
  background: var(--surface); border-right: 1px solid var(--line);
}}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1480px; }}

/* ---- type ------------------------------------------------------------- */
html, body, [class*="css"], .stMarkdown, p, li, label, span, div {{
  font-family: 'Instrument Sans', ui-sans-serif, system-ui, sans-serif;
  color: var(--ink);
}}
h1, h2, h3, h4 {{ color: var(--ink); letter-spacing: -.015em; }}
h1 {{ font-family:'Newsreader', Georgia, serif; font-weight:500; font-size:2.05rem;
     letter-spacing:-.02em; margin-bottom:.15rem; }}
h2 {{ font-size:1.12rem; font-weight:600; }}
h3 {{ font-size:.98rem; font-weight:600; }}
hr {{ border-color: var(--lineSoft); }}

/* section eyebrow: names the layer of the pipeline you are looking at */
.eyebrow {{
  font-family:'IBM Plex Mono', monospace; font-size:.68rem; font-weight:500;
  letter-spacing:.16em; text-transform:uppercase; color: var(--muted);
  display:flex; align-items:center; gap:.6rem; margin:.2rem 0 .7rem;
}}
.eyebrow::after {{ content:''; flex:1; height:1px; background: var(--lineSoft); }}

/* ---- instrument readouts --------------------------------------------- */
.rowgrid {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; }}
@media (max-width:1100px) {{ .rowgrid {{ grid-template-columns:repeat(3,1fr); }} }}
@media (max-width:640px)  {{ .rowgrid {{ grid-template-columns:repeat(2,1fr); }} }}

.tile {{
  background: var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:13px 14px 12px; box-shadow: var(--shadow); position:relative;
  overflow:hidden;
}}
.tile::before {{
  content:''; position:absolute; left:0; top:0; bottom:0; width:2px;
  background: var(--accentCol, var(--line));
}}
.tile .lab {{
  font-family:'IBM Plex Mono', monospace; font-size:.63rem; font-weight:500;
  letter-spacing:.13em; text-transform:uppercase; color: var(--muted);
}}
.tile .val {{
  font-family:'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  font-size:1.62rem; font-weight:500; line-height:1.15; margin-top:.28rem;
  color: var(--ink); letter-spacing:-.02em;
}}
.tile .val .u {{ font-size:.8rem; color: var(--muted); margin-left:.12rem; }}
.tile .dl {{
  font-family:'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  font-size:.7rem; margin-top:.3rem; color: var(--muted);
}}
.tile .dl b {{ font-weight:500; }}
.up {{ color: var(--ok); }} .dn {{ color: var(--danger); }} .fl {{ color: var(--muted); }}

/* ---- condition chips -------------------------------------------------- */
.strip {{ display:flex; flex-wrap:wrap; gap:8px; margin:.1rem 0 .9rem; }}
.chip {{
  display:inline-flex; align-items:center; gap:.5rem; padding:6px 12px 6px 10px;
  border-radius:999px; font-size:.775rem; font-weight:500; letter-spacing:.005em;
  border:1px solid transparent;
}}
.chip .dot {{ width:7px; height:7px; border-radius:50%; flex:none; }}
.chip.ok     {{ background:var(--okBg);     color:var(--ok);     border-color:color-mix(in srgb, var(--ok) 26%, transparent); }}
.chip.ok .dot     {{ background:var(--ok); }}
.chip.water  {{ background:var(--waterBg);  color:var(--water);  border-color:color-mix(in srgb, var(--water) 30%, transparent); }}
.chip.water .dot  {{ background:var(--water); }}
.chip.warn   {{ background:var(--warnBg);   color:var(--warn);   border-color:color-mix(in srgb, var(--warn) 32%, transparent); }}
.chip.warn .dot   {{ background:var(--warn); }}
.chip.danger {{ background:var(--dangerBg); color:var(--danger); border-color:color-mix(in srgb, var(--danger) 32%, transparent); }}
.chip.danger .dot {{ background:var(--danger); animation:pulse 1.8s ease-in-out infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.35}} }}
@media (prefers-reduced-motion: reduce) {{ .chip.danger .dot {{ animation:none; }} }}

/* ---- panels ----------------------------------------------------------- */
.panel {{
  background: var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:16px 18px; box-shadow: var(--shadow);
}}
.panel .cap {{
  font-family:'IBM Plex Mono', monospace; font-size:.63rem; letter-spacing:.13em;
  text-transform:uppercase; color:var(--muted); margin-bottom:.45rem;
}}
.panel .big {{
  font-family:'IBM Plex Mono', monospace; font-variant-numeric:tabular-nums;
  font-size:1.5rem; font-weight:500; letter-spacing:-.02em;
}}
.panel .sub {{ font-size:.76rem; color:var(--muted); margin-top:.3rem; line-height:1.45; }}

/* author card, top left */
.idcard {{
  display:inline-flex; align-items:center; gap:14px;
  background:var(--surface); border:1px solid var(--line); border-radius:11px;
  padding:9px 15px; box-shadow:var(--shadow); margin-bottom:.85rem;
}}
.idcard .nm {{
  font-family:'Instrument Sans', sans-serif; font-weight:600; font-size:.92rem;
  color:var(--ink); letter-spacing:-.01em; line-height:1.2;
}}
.idcard .rule {{ width:1px; align-self:stretch; background:var(--line); }}
.idcard .meta {{
  font-family:'IBM Plex Mono', monospace; font-size:.7rem; color:var(--muted);
  line-height:1.5; font-variant-numeric:tabular-nums;
}}
.idcard .meta b {{ color:var(--ink2); font-weight:500; }}

.clockline {{
  font-family:'IBM Plex Mono', monospace; font-size:.76rem; color:var(--muted);
  font-variant-numeric:tabular-nums;
}}
.clockline b {{ color:var(--ink2); font-weight:500; }}

/* ---- streamlit widget polish ------------------------------------------ */
[data-testid="stMetric"] {{
  background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:12px 14px;
}}
[data-testid="stMetricValue"] {{ font-family:'IBM Plex Mono',monospace;
  font-variant-numeric:tabular-nums; font-weight:500; }}
.stTabs [data-baseweb="tab-list"] {{ gap:2px; border-bottom:1px solid var(--line); }}
.stTabs [data-baseweb="tab"] {{
  font-size:.82rem; font-weight:500; color:var(--muted);
  padding:8px 14px; border-radius:8px 8px 0 0;
}}
.stTabs [aria-selected="true"] {{ color:var(--ink); background:var(--surface2); }}
.stButton button {{
  border-radius:9px; border:1px solid var(--line); font-weight:500; font-size:.82rem;
  background:var(--surface); color:var(--ink); transition:border-color .15s, transform .06s;
}}
.stButton button:hover {{ border-color:var(--water); color:var(--water); }}
.stButton button:active {{ transform:translateY(1px); }}
[data-testid="stSidebar"] h1 {{ font-size:1.05rem; font-family:'Instrument Sans',sans-serif;
  font-weight:600; letter-spacing:0; }}
[data-testid="stSidebar"] .stMarkdown p {{ font-size:.82rem; }}
[data-testid="stExpander"] {{ border:1px solid var(--line); border-radius:12px;
  background:var(--surface); }}
[data-testid="stDataFrame"] {{ border:1px solid var(--line); border-radius:10px; }}
:focus-visible {{ outline:2px solid var(--water); outline-offset:2px; }}

/* appearance switch, top right of the page */
div[data-testid="stSegmentedControl"] {{ display:flex; justify-content:flex-end; }}
div[data-testid="stSegmentedControl"] button {{
  font-size:.76rem; font-weight:500; padding:4px 12px;
}}
</style>"""
    st.markdown("\n".join(line.lstrip() for line in css.splitlines()),
                unsafe_allow_html=True)


# --------------------------------------------------------------------------
# PLOTLY
# --------------------------------------------------------------------------
def plotly_layout(mode, height=None):
    p = palette(mode)
    lay = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Mono, monospace", size=11, color=p["muted"]),
        margin=dict(l=8, r=8, t=34, b=8),
        hoverlabel=dict(bgcolor=p["surface"], bordercolor=p["line"],
                        font=dict(color=p["ink"], family="IBM Plex Mono, monospace")),
        legend=dict(font=dict(color=p["muted"], size=10)),
    )
    if height:
        lay["height"] = height
    return lay


def plotly_axes(fig, mode):
    p = palette(mode)
    fig.update_xaxes(showgrid=True, gridcolor=p["grid"], zeroline=False,
                     linecolor=p["line"], tickfont=dict(color=p["muted"], size=10))
    fig.update_yaxes(showgrid=True, gridcolor=p["grid"], zeroline=False,
                     linecolor=p["line"], tickfont=dict(color=p["muted"], size=10))
    for a in fig.layout.annotations or []:
        a.font.color = p["muted"]
        a.font.size = 11
    return fig


SERIES = {
    "temperature_c": ("Temperature", "°C", "danger"),
    "humidity_pct": ("Humidity", "%", "water"),
    "soil_moisture_pct": ("Soil moisture", "%", "soil"),
    "light_pct": ("Light", "%", "warn"),
    "water_level_pct": ("Tank level", "%", "ok"),
}


def series_colour(mode, key):
    return palette(mode)[SERIES[key][2]]


def alpha(hex_colour, a):
    """Plotly rejects 8-digit hex, so translucency has to go through rgba()."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{a})"


# --------------------------------------------------------------------------
# COMPONENTS
# --------------------------------------------------------------------------
def status_strip(items):
    """items: list of (label, kind) where kind in ok|water|warn|danger."""
    chips = "".join(
        f'<span class="chip {k}"><span class="dot"></span>{lab}</span>' for lab, k in items)
    st.markdown(tidy(f'<div class="strip">{chips}</div>'), unsafe_allow_html=True)


def eyebrow(text):
    st.markdown(tidy(f'<div class="eyebrow">{text}</div>'), unsafe_allow_html=True)


def readout_row(mode, tiles):
    """tiles: list of dicts {label, value, unit, delta, colour}."""
    p = palette(mode)
    cells = []
    for t in tiles:
        d = t.get("delta")
        if d is None:
            dl = '<span class="fl">—</span>'
        elif isinstance(d, str):
            dl = f'<span class="fl">{d}</span>'
        else:
            cls = "up" if d > 0.05 else ("dn" if d < -0.05 else "fl")
            arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "—")
            dl = f'<span class="{cls}">{arrow} <b>{abs(d):.1f}</b></span>'
        accent = p.get(t.get("colour", "line"), p["line"])
        cells.append(
            f'<div class="tile" style="--accentCol:{accent}">'
            f'<div class="lab">{t["label"]}</div>'
            f'<div class="val">{t["value"]}<span class="u">{t.get("unit","")}</span></div>'
            f'<div class="dl">{dl} <span style="opacity:.55">{t.get("note","")}</span></div>'
            f'</div>')
    st.markdown(tidy(f'<div class="rowgrid">{"".join(cells)}</div>'), unsafe_allow_html=True)


def soil_core(mode, current, predicted=None, low=35.0, high=60.0,
              wilting=9.0, capacity=62.0, top=75.0, height=196):
    """
    SIGNATURE ELEMENT. A soil core read bottom-up, with the control law drawn on
    the same axis as the measurement:

        · the hatched band below the wilting point is unavailable water
        · the tinted band between the two set-points is the controller dead band
        · the filled column is the current reading
        · the caret is the model's t+30 forecast

    A progress bar can show the level. Only this can show the level *and* the
    decision rule that acts on it, which is the thing an operator is judging.
    """
    p = palette(mode)
    W, H = 260, height
    pad_t, pad_b = 14, 22
    plot_h = H - pad_t - pad_b

    def y(v):
        return pad_t + plot_h * (1 - min(max(v, 0), top) / top)

    fill = p["soil"]
    band = p["ok"]
    dead_top, dead_bot = y(high), y(low)

    caret = ""
    if predicted is not None:
        yp = y(predicted)
        col = p["danger"] if predicted < low else p["water"]
        caret = f'''
      <polygon points="{W-58},{yp} {W-49},{yp-5} {W-49},{yp+5}" fill="{col}"/>
      <line x1="{W-58}" y1="{yp}" x2="86" y2="{yp}" stroke="{col}"
            stroke-width="1.2" stroke-dasharray="3 3" opacity=".85"/>
      <text x="{W-45}" y="{yp+3.5}" font-size="9.5" fill="{col}"
            font-family="IBM Plex Mono, monospace">{predicted:.1f}</text>'''

    return tidy(f'''
<svg viewBox="0 0 {W} {H}" width="100%" height="{H}" role="img"
     aria-label="Soil core: current moisture {current:.1f} percent, target band {low:.0f} to {high:.0f} percent">
  <defs>
    <linearGradient id="core{mode}" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%"  stop-color="{fill}" stop-opacity=".95"/>
      <stop offset="100%" stop-color="{fill}" stop-opacity=".55"/>
    </linearGradient>
    <pattern id="hatch{mode}" width="6" height="6" patternTransform="rotate(45)"
             patternUnits="userSpaceOnUse">
      <line x1="0" y1="0" x2="0" y2="6" stroke="{p['muted']}" stroke-width="1" opacity=".35"/>
    </pattern>
  </defs>

  <!-- dead band -->
  <rect x="30" y="{dead_top}" width="56" height="{dead_bot-dead_top}"
        fill="{band}" opacity=".13"/>
  <line x1="30" y1="{dead_bot}" x2="86" y2="{dead_bot}" stroke="{p['danger']}"
        stroke-width="1" stroke-dasharray="4 3"/>
  <line x1="30" y1="{dead_top}" x2="86" y2="{dead_top}" stroke="{band}" stroke-width="1"
        stroke-dasharray="4 3"/>
  <text x="92" y="{dead_bot+3.5}" font-size="9" fill="{p['danger']}"
        font-family="IBM Plex Mono, monospace">{low:.0f} start</text>
  <text x="92" y="{dead_top+3.5}" font-size="9" fill="{band}"
        font-family="IBM Plex Mono, monospace">{high:.0f} stop</text>

  <!-- unavailable water -->
  <rect x="30" y="{y(wilting)}" width="56" height="{H-pad_b-y(wilting)}"
        fill="url(#hatch{mode})"/>
  <text x="92" y="{y(wilting)+3.5}" font-size="9" fill="{p['muted']}"
        font-family="IBM Plex Mono, monospace">{wilting:.0f} wilting</text>

  <!-- column -->
  <rect x="30" y="{pad_t}" width="56" height="{plot_h}" fill="none"
        stroke="{p['line']}" stroke-width="1" rx="3"/>
  <rect x="31" y="{y(current)}" width="54" height="{H-pad_b-y(current)}"
        fill="url(#core{mode})" rx="2"/>
  <line x1="30" y1="{y(current)}" x2="86" y2="{y(current)}" stroke="{p['ink']}"
        stroke-width="1.6"/>
  <text x="30" y="{max(y(current)-6, 11)}" font-size="13" fill="{p['ink']}"
        font-weight="600" font-family="IBM Plex Mono, monospace">{current:.1f}%</text>
  {caret}
  <text x="30" y="{H-6}" font-size="8.5" fill="{p['muted']}"
        letter-spacing="1.4" font-family="IBM Plex Mono, monospace">ROOT ZONE</text>
</svg>''')


def score_meter(mode, score, threshold, lo=-0.12, hi=0.12, height=64):
    """Anomaly score placed on its decision boundary, so the margin is visible."""
    p = palette(mode)
    W = 300
    def x(v):
        return 10 + (W - 20) * (min(max(v, lo), hi) - lo) / (hi - lo)
    flagged = score >= threshold
    col = p["danger"] if flagged else p["ok"]
    return tidy(f'''
<svg viewBox="0 0 {W} {height}" width="100%" height="{height}" role="img"
     aria-label="Anomaly score {score:.4f}, boundary {threshold:.4f}">
  <rect x="10" y="20" width="{x(threshold)-10}" height="8" rx="4" fill="{p['ok']}" opacity=".22"/>
  <rect x="{x(threshold)}" y="20" width="{W-10-x(threshold)}" height="8" rx="4"
        fill="{p['danger']}" opacity=".22"/>
  <line x1="{x(threshold)}" y1="14" x2="{x(threshold)}" y2="34" stroke="{p['muted']}"
        stroke-width="1.2"/>
  <text x="{x(threshold)}" y="46" font-size="8.5" fill="{p['muted']}" text-anchor="middle"
        font-family="IBM Plex Mono, monospace">boundary</text>
  <circle cx="{x(score)}" cy="24" r="6" fill="{col}" stroke="{p['surface']}" stroke-width="2"/>
  <text x="{x(score)}" y="12" font-size="9.5" fill="{col}" text-anchor="middle"
        font-family="IBM Plex Mono, monospace">{score:+.4f}</text>
  <text x="10" y="60" font-size="8" fill="{p['muted']}"
        font-family="IBM Plex Mono, monospace">NORMAL</text>
  <text x="{W-10}" y="60" font-size="8" fill="{p['muted']}" text-anchor="end"
        font-family="IBM Plex Mono, monospace">ANOMALOUS</text>
</svg>''')


def confidence_bar(mode, prob, height=34):
    """Classifier probability with the 0.5 decision point marked."""
    p = palette(mode)
    W = 300
    col = p["water"] if prob >= .5 else p["muted"]
    w = max((W - 20) * min(max(prob, 0), 1), 2)
    return tidy(f'''
<svg viewBox="0 0 {W} {height}" width="100%" height="{height}" role="img"
     aria-label="Model confidence {prob:.0%}">
  <rect x="10" y="10" width="{W-20}" height="9" rx="4.5" fill="{p['line']}" opacity=".55"/>
  <rect x="10" y="10" width="{w}" height="9" rx="4.5" fill="{col}"/>
  <line x1="{10+(W-20)*.5}" y1="6" x2="{10+(W-20)*.5}" y2="23" stroke="{p['muted']}"
        stroke-width="1"/>
  <text x="10" y="31" font-size="8.5" fill="{p['muted']}"
        font-family="IBM Plex Mono, monospace">{prob:.1%} confidence</text>
  <text x="{W-10}" y="31" font-size="8.5" fill="{p['muted']}" text-anchor="end"
        font-family="IBM Plex Mono, monospace">decides at 50%</text>
</svg>''')
