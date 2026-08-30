import base64
import os, requests, pandas as pd, streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="TwinLine AI Dashboard", layout="wide")

API = os.getenv("TWINLINE_API", "http://localhost:8000")
REFRESH_MS = int(os.getenv("TWINLINE_REFRESH_MS", "4000"))
HISTORY_POINTS = int(os.getenv("TWINLINE_HISTORY_POINTS", "60"))


GREEN, YELLOW, RED, GREY, INK = "#16A34A", "#D97706", "#DC2626", "#8A94A3", "#26313C"

PAGE_BG = "#DEFDED"
CARD_BG = "#FBF3E1"      # cream
GRID_LINE = "#E7E0CF"
MUTED = "#8A7F6E"


ACCENTS = ["#0EA5E9", "#8B5CF6", "#F97316", "#EC4899", "#14B8A6", "#F59E0B"]

LOGO_PATH = os.path.join(os.path.dirname(__file__), "InnovastraLogo.png")
ACCENTURE_LOGO_PATH = os.path.join(os.path.dirname(__file__), "AccentureLogo.png")

st.markdown(f"""
<style>

/* ============================================================
   GLOBAL PAGE
   ============================================================ */

.stApp {{
    background-color: {PAGE_BG};
}}

.block-container {{
    padding-top: 1rem !important;
    padding-bottom: 1.2rem;
    max-width: 1500px;
}}


[data-testid="stHeader"] {{
    display: none;
}}


h1 {{
    font-size: 1.7rem !important;
    margin-bottom: 0 !important;
}}

h3 {{
    margin-top: 0.3rem !important;
    margin-bottom: 0.4rem !important;
}}

hr {{
    margin: 0.6rem 0 !important;
}}


.tl-card {{
    background: {CARD_BG};
    border-radius: 12px;
    padding: 10px 14px;
    border-left: 5px solid #333;
    margin-bottom: 8px;
    box-shadow: 0 1px 4px rgba(90, 70, 30, 0.10);
}}

.tl-card-label {{
    font-size: 0.75rem;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 2px;
    font-weight: 600;
}}

.tl-card-value {{
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.1;
}}

.tl-card-value-lg {{
    font-size: 2.6rem;
    font-weight: 800;
    line-height: 1.05;
}}

.tl-card-sub {{
    font-size: 0.75rem;
    color: {MUTED};
    margin-top: 2px;
}}



.tl-badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
}}


.tl-powered {{
    text-align: right;
    color: {MUTED};
    font-size: 0.85rem;
    font-style: italic;
    padding-top: 22px;
}}

[data-testid="stDataFrame"] {{
    background-color: {CARD_BG};
    border-radius: 10px;
    padding: 4px;
}}

/* Container gap */
[data-baseweb="tab-list"], [data-testid="stTabs"] {{
    gap: 6px !important;
}}

/* Base style for all tab headers */
[data-baseweb="tab"], 
[data-testid="stTab"] {{
    font-size: 1.02rem !important;
    font-weight: 600 !important;
    padding: 9px 14px !important;
    border-radius: 8px !important;
    border: none !important;
}}

/* Active tab background */
[data-baseweb="tab"][aria-selected="true"],
[data-testid="stTab"][aria-selected="true"] {{
    background-color: #F97316 !important;
}}

/* Active tab text color override */
[data-baseweb="tab"][aria-selected="true"] *,
[data-testid="stTab"][aria-selected="true"] *,
[data-baseweb="tab"][aria-selected="true"] p,
[data-testid="stTab"][aria-selected="true"] p {{
    color: #000000 !important;
    -webkit-text-fill-color: #000000 !important;
}}

/* Inactive tabs styling */
[data-baseweb="tab"][aria-selected="false"],
[data-testid="stTab"][aria-selected="false"] {{
    background-color: rgba(0, 0, 0, 0.04) !important;
}}

[data-baseweb="tab"][aria-selected="false"] *,
[data-testid="stTab"][aria-selected="false"] *,
[data-baseweb="tab"][aria-selected="false"] p,
[data-testid="stTab"][aria-selected="false"] p {{
    color: {INK} !important;
    -webkit-text-fill-color: {INK} !important;
}}

/* Remove default active highlight bar */
[data-baseweb="tab-highlight"], 
[data-testid="stTabHighlight"] {{
    display: none !important;
}}

</style>
""", unsafe_allow_html=True)


def stat_card(col, label, value, color=INK, sub=None, size="normal"):
    value_class = "tl-card-value-lg" if size == "lg" else "tl-card-value"
    col.markdown(f"""
    <div class="tl-card" style="border-left-color:{color}">
        <div class="tl-card-label">{label}</div>
        <div class="{value_class}" style="color:{color}">{value}</div>
        {f'<div class="tl-card-sub">{sub}</div>' if sub else ''}
    </div>
    """, unsafe_allow_html=True)


def gauge(title, value, max_value=100, invert=False, suffix=""):
    """invert=False -> higher is better (green at top end). invert=True -> lower is better (green at bottom end)."""
    lo_c, mid_c, hi_c = (GREEN, YELLOW, RED) if invert else (RED, YELLOW, GREEN)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={'suffix': suffix, 'font': {'color': INK, 'size': 32}},
        title={'text': title, 'font': {'size': 14, 'color': INK}},
        gauge={
            'axis': {'range': [0, max_value], 'tickcolor': '#B9AE97'},
            'bar': {'color': INK, 'thickness': 0.25},
            'bgcolor': "rgba(0,0,0,0)",
            'borderwidth': 0,
            'steps': [
                {'range': [0, max_value * 0.5], 'color': lo_c},
                {'range': [max_value * 0.5, max_value * 0.8], 'color': mid_c},
                {'range': [max_value * 0.8, max_value], 'color': hi_c},
            ],
        }
    ))
    fig.update_layout(height=190, margin=dict(l=20, r=20, t=40, b=10),
                       paper_bgcolor="rgba(0,0,0,0)", font_color=INK)
    st.plotly_chart(fig, use_container_width=True)


def styled_bar(x, y, colors, title, yrange=None, bar_width=None):
    bar_kwargs = dict(x=x, y=y, marker_color=colors)
    if bar_width is not None:
        bar_kwargs["width"] = bar_width
    fig = go.Figure(go.Bar(**bar_kwargs))
    fig.update_layout(height=220, margin=dict(l=10, r=10, t=35, b=10),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       font_color=INK, title=title,
                       xaxis=dict(gridcolor=GRID_LINE), yaxis=dict(gridcolor=GRID_LINE, range=yrange))
    st.plotly_chart(fig, use_container_width=True)


def pretty(df):
    """Table headers without underscores, e.g. 'health_score' -> 'health score'."""
    return df.rename(columns=lambda c: c.replace("_", " "))


def status_color(status):
    s = (str(status) if status is not None else "").strip().title()
    if s == "Running":
        return GREEN
    if s in ("Fault", "Blocked", "Starved"):
        return RED
    if s == "":
        return GREY
    return YELLOW


def health_color(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return GREY
    if v >= 80:
        return GREEN
    if v >= 50:
        return YELLOW
    return RED


def severity_color(sev):
    s = (str(sev) if sev is not None else "").strip().title()
    if s == "Low":
        return health_color(80)
    if s == "Medium":
        return health_color(65)
    if s in ("High", "Critical"):
        return health_color(20)
    return GREY


def risk_color(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return GREY
    if p < 0.3:
        return GREEN
    if p < 0.6:
        return YELLOW
    return RED


def pct_color(v):
    """For *_reduction_pct / *_improvement_pct fields, where positive = good."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return GREY
    if v > 5:
        return GREEN
    if v >= 0:
        return YELLOW
    return RED


def cell_style(color):
    return f"background-color:{color}33; color:{color}; font-weight:600"


def style_map(styler, func, subset):
    """Styler.applymap was removed in newer pandas (renamed to .map); support both."""
    if hasattr(styler, "map"):
        return styler.map(func, subset=subset)
    return styler.applymap(func, subset=subset)


col_logo, col_title, col_powered = st.columns([1.5, 5, 1.6])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=110, )
with col_title:
    st.title("TwinLine AI Dashboard")
    st.caption("Live digital-twin monitoring, bottleneck prediction & business-value KPIs")
with col_powered:
    if os.path.exists(ACCENTURE_LOGO_PATH):
        with open(ACCENTURE_LOGO_PATH, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()

        st.markdown(
            f"""
            <div style="
                display:flex;
                align-items:center;
                justify-content:flex-end;
                gap:10px;
                padding-top:18px;
            ">
                <img src="data:image/png;base64,{logo_b64}"
                     style="width:55px; height:auto;">
                <span style="
                    color:{MUTED};
                    font-size:0.85rem;
                    font-style:italic;
                    white-space:nowrap;
                ">
                    Powered by Accenture
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

st_autorefresh(interval=REFRESH_MS, key="datarefresh")

try:
    summary = requests.get(API + "/line-summary", timeout=8).json()
    stations = requests.get(API + "/stations", timeout=8).json()
    alerts = requests.get(API + "/alerts", timeout=8).json()
    preds = requests.get(API + "/predictions", timeout=8).json()
except Exception as e:
    st.error(f"Backend not reachable at {API}. Start FastAPI first. ({e})")
    st.stop()

try:
    _history_resp = requests.get(API + "/history", params={"points_per_station": HISTORY_POINTS}, timeout=8).json()
    history = _history_resp if isinstance(_history_resp, list) else []
except Exception:
    history = []

df_stations_top = pd.DataFrame(stations).T if stations else pd.DataFrame()
total_capacity, total_std_cycle, n_stations_top = 0.0, 0.0, 0
if not df_stations_top.empty:
    total_capacity = pd.to_numeric(df_stations_top.get("station_capacity"), errors="coerce").fillna(0).sum()
    total_std_cycle = pd.to_numeric(df_stations_top.get("standard_cycle_time"), errors="coerce").fillna(0).mean()
    n_stations_top = len(df_stations_top)

avg_health = summary.get("avg_health", 100) or 100
total_wip = summary.get("total_wip", 0) or 0
avg_cycle_time = summary.get("avg_cycle_time", 0) or 0
wip_ratio = (total_wip / total_capacity) if total_capacity else 0
cycle_dev = (abs(avg_cycle_time - total_std_cycle) / total_std_cycle) if total_std_cycle else 0

wip_color = GREEN if wip_ratio < 0.7 else YELLOW if wip_ratio < 0.9 else (RED if total_capacity else INK)
cycle_color = GREEN if cycle_dev <= 0.10 else YELLOW if cycle_dev <= 0.25 else (RED if total_std_cycle else INK)

# --------------------------- Top overview: 2x2 grid + gauge ------------------
head1, head2 = st.columns([2, 1])
with head1:
    r1c1, r1c2 = st.columns(2)
    r2c1, r2c2 = st.columns(2)
    stat_card(r1c1, "Stations", summary.get("stations", 0), color=ACCENTS[0], size="lg")
    stat_card(r1c2, "Line Health", f"{avg_health:.1f}", color=health_color(avg_health), size="lg")
    stat_card(r2c1, "Total WIP", f"{total_wip:.0f}",
              color=wip_color, sub=(f"of {total_capacity:.0f} capacity" if total_capacity else None), size="lg")
    stat_card(r2c2, "Avg Cycle Time", f"{avg_cycle_time:.1f}s",
              color=cycle_color, sub=(f"vs {total_std_cycle:.1f}s std" if total_std_cycle else None), size="lg")
with head2:
    gauge("Line Health Score", round(float(avg_health), 1), max_value=100, invert=False)

st.divider()

tab1, tab2, tab3, tab4 = st.tabs(
    ["Live Line Dashboard", "Live Diagnostics", "Prediction Cockpit", "Business KPIs"]
)

with tab1:
    st.subheader("Live Station State")
    if stations:
        df_st = pd.DataFrame(stations).T
        for c in ("utilization", "current_wip", "station_capacity", "cycle_time", "vibration", "temperature"):
            if c in df_st.columns:
                df_st[c] = pd.to_numeric(df_st[c], errors="coerce")

        status_counts = df_st["station_status"].value_counts().to_dict() if "station_status" in df_st else {}
        running = status_counts.get("Running", 0)
        down = sum(status_counts.get(s, 0) for s in ("Fault", "Blocked", "Starved"))
        other = sum(v for k, v in status_counts.items() if k not in ("Running", "Fault", "Blocked", "Starved"))

        c1, c2, c3, c4 = st.columns(4)
        stat_card(c1, "Total Stations", len(df_st), color=ACCENTS[1])
        stat_card(c2, "Running", running, color=GREEN)
        stat_card(c3, "Idle / Other", other, color=YELLOW)
        stat_card(c4, "Down (Fault/Blocked/Starved)", down, color=RED)

        gcol, dcol = st.columns([1, 2])
        with gcol:
            if status_counts:
                fig = go.Figure(go.Pie(
                    labels=list(status_counts.keys()), values=list(status_counts.values()),
                    marker=dict(colors=[status_color(k) for k in status_counts.keys()]),
                    hole=0.55
                ))
                fig.update_layout(height=220, margin=dict(l=10, r=10, t=35, b=10),
                                   paper_bgcolor="rgba(0,0,0,0)", font_color=INK,
                                   title="Station Status Mix", showlegend=True)
                st.plotly_chart(fig, use_container_width=True)
        with dcol:
            if "utilization" in df_st.columns:
                u = df_st["utilization"].fillna(0)
                colors = [GREEN if v >= 0.85 else YELLOW if v >= 0.6 else RED for v in u]
                styled_bar(
                    df_st["station_id"], u, colors, "Utilization by Station",
                    yrange=[0, 1], bar_width=0.55
                )

        def _status_style(v):
            return cell_style(status_color(v))

        def _util_style(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                return ""
            c = GREEN if v >= 0.85 else YELLOW if v >= 0.6 else RED
            return cell_style(c)

        def _wip_row_style(row):
            try:
                wip, cap = float(row.get("current wip", 0)), float(row.get("station capacity", 0))
                ratio = wip / cap if cap > 0 else 0
            except (TypeError, ValueError):
                ratio = 0
            c = GREEN if ratio < 0.7 else YELLOW if ratio < 0.9 else RED
            return [cell_style(c) if col == "current wip" else "" for col in row.index]

        df_st_disp = pretty(df_st)
        styler = df_st_disp.style
        if "station status" in df_st_disp.columns:
            styler = style_map(styler, _status_style, ["station status"])
        if "utilization" in df_st_disp.columns:
            styler = style_map(styler, _util_style, ["utilization"])
        if "current wip" in df_st_disp.columns and "station capacity" in df_st_disp.columns:
            styler = styler.apply(_wip_row_style, axis=1)
        st.dataframe(styler, use_container_width=True)
    else:
        st.info("No station data yet — start publish_csv.py to see live readings here.")

    st.subheader("Real-time Anomaly Alerts")
    df_al = pd.DataFrame(alerts)
    if not df_al.empty:
        sev_counts = df_al["severity"].value_counts().to_dict() if "severity" in df_al else {}
        a1, a2, a3 = st.columns(3)
        stat_card(a1, "Low Severity", sev_counts.get("Low", 0), color=GREEN)
        stat_card(a2, "Medium Severity", sev_counts.get("Medium", 0), color=YELLOW)
        stat_card(a3, "High/Critical Severity", sev_counts.get("High", 0) + sev_counts.get("Critical", 0), color=RED)

        def _sev_style(v):
            return cell_style(severity_color(v))

        def _health_style(v):
            return cell_style(health_color(v))

        def _station_health_style(row):
            color = health_color(row.get("health score"))
            return [cell_style(color) if col == "station id" else "" for col in row.index]

        df_al_disp = pretty(df_al)
        styler_al = df_al_disp.style
        if "severity" in df_al_disp.columns:
            styler_al = style_map(styler_al, _sev_style, ["severity"])
        if "health score" in df_al_disp.columns:
            styler_al = style_map(styler_al, _health_style, ["health score"])
        if "station id" in df_al_disp.columns and "health score" in df_al_disp.columns:
            styler_al = styler_al.apply(_station_health_style, axis=1)
        st.dataframe(styler_al, use_container_width=True)
    else:
        st.dataframe(df_al, use_container_width=True)
        st.caption("No alerts above threshold yet — all stations nominal.")


with tab2:
    st.subheader("Live Diagnostics")
    df_h = pd.DataFrame(history) if isinstance(history, list) and history else pd.DataFrame()
    if df_h.empty:
        st.info("No history yet — once a few readings have streamed in, live trend "
                "heatmaps and sensor diagnostics will appear here.")
    else:
        for c in ("cycle_time", "vibration", "temperature", "current_wip", "takt_time", "step"):
            if c in df_h.columns:
                df_h[c] = pd.to_numeric(df_h[c], errors="coerce")

        hcol1, hcol2 = st.columns(2)
        with hcol1:
            pivot_ct = df_h.pivot_table(index="station_id", columns="step", values="cycle_time", aggfunc="mean")
            fig_ct = go.Figure(go.Heatmap(
                z=pivot_ct.values, x=pivot_ct.columns, y=pivot_ct.index,
                colorscale="YlOrBr", colorbar=dict(title="s")
            ))
            fig_ct.update_layout(title="Station Cycle Time — Recent Trend", height=280,
                                  margin=dict(l=10, r=10, t=35, b=10),
                                  paper_bgcolor="rgba(0,0,0,0)", font_color=INK,
                                  xaxis_title="Step", yaxis_title="Station")
            st.plotly_chart(fig_ct, use_container_width=True)
        with hcol2:
            pivot_vib = df_h.pivot_table(index="station_id", columns="step", values="vibration", aggfunc="mean")
            fig_vib = go.Figure(go.Heatmap(
                z=pivot_vib.values, x=pivot_vib.columns, y=pivot_vib.index,
                colorscale="Greys", colorbar=dict(title="vib")
            ))
            fig_vib.update_layout(title="Station Vibration — Recent Trend", height=280,
                                   margin=dict(l=10, r=10, t=35, b=10),
                                   paper_bgcolor="rgba(0,0,0,0)", font_color=INK,
                                   xaxis_title="Step", yaxis_title="Station")
            st.plotly_chart(fig_vib, use_container_width=True)

        risk_station = None
        if preds:
            df_p = pd.DataFrame(preds)
            if not df_p.empty and "bottleneck_probability" in df_p.columns and "station_id" in df_p.columns:
                df_p["bottleneck_probability"] = pd.to_numeric(df_p["bottleneck_probability"], errors="coerce").fillna(0)
                risk_station = df_p.loc[df_p["bottleneck_probability"].idxmax(), "station_id"]
        if risk_station is None or risk_station not in df_h["station_id"].values:
            vib_std = df_h.groupby("station_id")["vibration"].std()
            if not vib_std.empty:
                risk_station = vib_std.idxmax()

        if risk_station is not None:
            s_data = df_h[df_h["station_id"] == risk_station].sort_values("step")
            fig_sensor = go.Figure()
            fig_sensor.add_trace(go.Scatter(
                x=s_data["step"], y=s_data["vibration"],
                name="Vibration", line=dict(color="#7FA8A3", width=2)
            ))
            fig_sensor.add_trace(go.Scatter(
                x=s_data["step"], y=s_data["temperature"],
                name="Temperature", line=dict(color="#C58A82", width=2, dash="dot"),
                yaxis="y2"
            ))
            fig_sensor.update_layout(
                title=f"Sensor Diagnostics — {risk_station} (highest current risk)",
                height=280, margin=dict(l=10, r=10, t=35, b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=INK,
                xaxis=dict(title="Step", gridcolor=GRID_LINE),
                yaxis=dict(title="Vibration", gridcolor=GRID_LINE),
                yaxis2=dict(title="Temperature (°C)", overlaying="y", side="right"),
                legend=dict(orientation="h", y=1.15)
            )
            st.plotly_chart(fig_sensor, use_container_width=True)

with tab3:
    st.subheader("Bottleneck Predictions")
    df_pred = pd.DataFrame(preds)
    if not df_pred.empty:
        df_pred["bottleneck_probability"] = pd.to_numeric(df_pred.get("bottleneck_probability"), errors="coerce").fillna(0)
        high = int((df_pred["bottleneck_probability"] >= 0.6).sum())
        med = int(((df_pred["bottleneck_probability"] >= 0.3) & (df_pred["bottleneck_probability"] < 0.6)).sum())
        low = int((df_pred["bottleneck_probability"] < 0.3).sum())

        p1, p2, p3, p4 = st.columns(4)
        stat_card(p1, "Stations Tracked", len(df_pred), color=ACCENTS[2])
        stat_card(p2, "Low Risk", low, color=GREEN)
        stat_card(p3, "Medium Risk", med, color=YELLOW)
        stat_card(p4, "High Risk", high, color=RED)

        gcol2, bcol2 = st.columns([1, 2])
        with gcol2:
            gauge("Avg. Bottleneck Risk", round(df_pred["bottleneck_probability"].mean() * 100, 1),
                  max_value=100, invert=True, suffix="%")
        with bcol2:
            sorted_df = df_pred.sort_values("bottleneck_probability", ascending=False)
            colors = [risk_color(p) for p in sorted_df["bottleneck_probability"]]
            styled_bar(sorted_df["station_id"], sorted_df["bottleneck_probability"], colors,
                       "Bottleneck Probability by Station", yrange=[0, 1])

        def _risk_style(v):
            return cell_style(risk_color(v))

        df_pred_disp = pretty(df_pred)
        styler_pred = df_pred_disp.style
        if "bottleneck probability" in df_pred_disp.columns:
            styler_pred = style_map(styler_pred, _risk_style, ["bottleneck probability"])
        st.dataframe(styler_pred, use_container_width=True)
    else:
        st.dataframe(df_pred, use_container_width=True)
        st.caption("No predictions yet.")

with tab4:
    st.subheader("Downtime, Throughput & Peak WIP — Before vs. After Early Warning")
    try:
        kpi = requests.get(API + "/kpi", timeout=5).json()
    except Exception:
        kpi = None

    if not kpi or not kpi.get("per_station"):
        st.info("Not enough ingested data yet to compute business-value KPIs. "
                "Stream a few normal + anomalous entries first.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Downtime", f"{kpi['downtime_after_sec']:.0f}s",
                   f"{kpi['downtime_reduction_pct']:.1f}% vs. before", delta_color="inverse")
        c2.metric("Throughput", f"{kpi['throughput_after_vph']:.1f} vph",
                   f"{kpi['throughput_improvement_pct']:.1f}% vs. before")
        c3.metric("Peak WIP", f"{kpi['peak_wip_after']:.0f}",
                   f"{kpi['peak_wip_reduction_pct']:.1f}% vs. before", delta_color="inverse")

        composite = (kpi['downtime_reduction_pct'] + kpi['throughput_improvement_pct']
                     + kpi['peak_wip_reduction_pct']) / 3.0
        gauge_val = max(0.0, min(100.0, composite + 50.0))

        gcol3, chartcol3 = st.columns([1, 2])
        with gcol3:
            gauge("Overall Improvement Score", round(gauge_val, 1), max_value=100)
            st.caption(f"Composite of downtime/throughput/peak-WIP change: {composite:+.1f}%")
        with chartcol3:
            fig4 = go.Figure()
            fig4.add_bar(name="Before", x=["Downtime (s)", "Throughput (vph)", "Peak WIP"],
                         y=[kpi["downtime_before_sec"], kpi["throughput_before_vph"], kpi["peak_wip_before"]],
                         marker_color="#D6CCB8")
            fig4.add_bar(name="After", x=["Downtime (s)", "Throughput (vph)", "Peak WIP"],
                         y=[kpi["downtime_after_sec"], kpi["throughput_after_vph"], kpi["peak_wip_after"]],
                         marker_color=GREEN)
            fig4.update_layout(barmode="group", height=220, margin=dict(l=10, r=10, t=35, b=10),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                font_color=INK, title="Before vs. After",
                                xaxis=dict(gridcolor=GRID_LINE), yaxis=dict(gridcolor=GRID_LINE))
            st.plotly_chart(fig4, use_container_width=True)

        st.subheader("Per-Station Breakdown")
        df_ps = pd.DataFrame(kpi["per_station"])
        if not df_ps.empty:
            df_ps["downtime_reduction_pct"] = df_ps.apply(
                lambda r: ((r["downtime_before_sec"] - r["downtime_after_sec"]) / r["downtime_before_sec"] * 100)
                if r.get("downtime_before_sec", 0) else 0.0, axis=1).round(1)
            df_ps["peak_wip_reduction_pct"] = df_ps.apply(
                lambda r: ((r["peak_wip_before"] - r["peak_wip_after"]) / r["peak_wip_before"] * 100)
                if r.get("peak_wip_before", 0) else 0.0, axis=1).round(1)

            def _pct_style(v):
                return cell_style(pct_color(v))

            df_ps_disp = pretty(df_ps)
            pct_cols = [c for c in ("downtime reduction pct", "peak wip reduction pct") if c in df_ps_disp.columns]
            styler_ps = df_ps_disp.style
            if pct_cols:
                styler_ps = style_map(styler_ps, _pct_style, pct_cols)
            st.dataframe(styler_ps, use_container_width=True)
        else:
            st.dataframe(df_ps, use_container_width=True)
