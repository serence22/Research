from __future__ import annotations

from io import BytesIO
import math

import altair as alt
import pandas as pd
import streamlit as st

from phosphorus_arrhenius_gui.core.analysis_pipeline import (
    AnalysisBundle,
    _fit_selected_intervals,
    run_analysis,
)
from phosphorus_arrhenius_gui.core.arrhenius_model import rate_from_fit
from phosphorus_arrhenius_gui.core.constants import CONDITION_015_AFTER_120, CONDITION_015_0_120
from phosphorus_arrhenius_gui.core.predictor import predict_loss_composite
from phosphorus_arrhenius_gui.core.schedule_optimizer import calculate_composite_schedule
from phosphorus_arrhenius_gui.core.summary_sheet_loader import build_summary_intervals, read_summary_sheet


DEFAULT_GOOGLE_SHEET = (
    "https://docs.google.com/spreadsheets/d/"
    "1Gg9XJk0p5_yHgD5lgZg9oyTWgkWT1sbZA-BtBs7GwVU/edit?gid=193585797#gid=193585797"
)


st.set_page_config(page_title="P Sublimation Analyzer", layout="wide")


def fmt(value: object, digits: int = 5) -> str:
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except Exception:
        pass
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


@st.cache_data(show_spinner=False)
def load_from_url(url: str) -> AnalysisBundle:
    return run_analysis(url)


def load_from_upload(data: bytes) -> AnalysisBundle:
    workbook = BytesIO(data)
    rows = read_summary_sheet(workbook)
    intervals = build_summary_intervals(rows)
    intervals["fitting_included"] = intervals["fitting_included"].fillna(False).astype(bool)
    summaries, fits, fit_logs = _fit_selected_intervals(intervals)
    logs = [
        "Data source: uploaded workbook, Codex/summary sheet only",
        f"Rows loaded: {len(rows)}",
        "Arrhenius fitting uses first-order k = -ln(p2/p1)/(t2-t1), in min^-1.",
    ] + fit_logs
    return AnalysisBundle(
        file_path="uploaded workbook",
        raw_formula=rows,
        raw_full=pd.DataFrame(),
        formula_intervals=intervals.copy(),
        full_intervals=pd.DataFrame(),
        intervals=intervals,
        summaries=summaries,
        fits=fits,
        logs=logs,
        base_logs=list(logs),
    )


def fit_label(name: str, fit, temperature_c: float) -> str:
    if not fit.is_valid:
        return f"{name}: fit unavailable"
    k = rate_from_fit(fit, temperature_c)
    return (
        f"{name}: Ea {fit.ea_kj_per_mol:.3g} kJ/mol | "
        f"R² {fit.r_squared:.4f} | k@{temperature_c:g}C {k:.6g} min⁻¹"
    )


def arrhenius_chart(bundle: AnalysisBundle) -> alt.Chart:
    point_rows: list[dict] = []
    line_rows: list[dict] = []
    for model_name, condition, color_name in [
        ("k1: 0-120 min", CONDITION_015_0_120, "#2563eb"),
        ("k2: After 120 min", CONDITION_015_AFTER_120, "#e11d48"),
    ]:
        summary = bundle.summaries[condition]
        fit = bundle.fits[condition]
        if summary.empty or not fit.is_valid:
            continue
        for row in summary.itertuples():
            k_value = float(row.representative_k_per_min)
            point_rows.append(
                {
                    "model": model_name,
                    "x": 1.0 / float(row.temperature_K),
                    "ln_k": math.log(k_value),
                    "temperature_C": float(row.temperature_C),
                    "k min^-1": k_value,
                    "color": color_name,
                }
            )
        x_values = [r["x"] for r in point_rows if r["model"] == model_name]
        if not x_values:
            continue
        x_min, x_max = min(x_values), max(x_values)
        for i in range(80):
            x = x_min + (x_max - x_min) * i / 79
            line_rows.append({"model": model_name, "x": x, "ln_k": fit.slope * x + fit.intercept})

    points = alt.Chart(pd.DataFrame(point_rows)).mark_circle(size=90).encode(
        x=alt.X("x:Q", title="1/T, K^-1"),
        y=alt.Y("ln_k:Q", title="ln(k), k in min^-1"),
        color=alt.Color("model:N", title="Model"),
        tooltip=["model", "temperature_C", "k min^-1", "ln_k"],
    )
    lines = alt.Chart(pd.DataFrame(line_rows)).mark_line(size=3).encode(
        x="x:Q",
        y="ln_k:Q",
        color=alt.Color("model:N", title="Model"),
    )
    return (points + lines).properties(height=430)


def prediction_chart(pred) -> alt.Chart:
    times = [pred.process_time_min * i / 120 for i in range(121)]
    rows = []
    for t in times:
        remaining = pred.initial_mass_mg
        for segment in pred.segments:
            if t <= segment.start_min:
                break
            duration = min(t, segment.end_min) - segment.start_min
            if duration > 0:
                remaining *= math.exp(-segment.k_per_min * duration)
        rows.append({"time_min": t, "value_mg": remaining, "series": "Remaining P"})
        rows.append({"time_min": t, "value_mg": pred.initial_mass_mg - remaining, "series": "Cumulative loss"})
    return (
        alt.Chart(pd.DataFrame(rows))
        .mark_line(size=3)
        .encode(
            x=alt.X("time_min:Q", title="Time, min"),
            y=alt.Y("value_mg:Q", title="P mass, mg"),
            color=alt.Color("series:N", title=""),
            tooltip=["series", "time_min", "value_mg"],
        )
        .properties(height=360)
    )


st.title("P Sublimation Analyzer")
st.caption("Online Streamlit version: Google Sheets or uploaded XLSX → Arrhenius k1/k2 → Prediction → Constant Rate Schedule")

with st.sidebar:
    st.header("Data source")
    source_mode = st.radio("Input type", ["Google Sheet URL", "Upload XLSX"], horizontal=False)
    url = st.text_input("Google Sheet URL", value=DEFAULT_GOOGLE_SHEET, disabled=source_mode != "Google Sheet URL")
    upload = st.file_uploader("XLSX file", type=["xlsx"], disabled=source_mode != "Upload XLSX")
    analyze = st.button("Analyze", type="primary", use_container_width=True)

if "bundle" not in st.session_state or analyze:
    try:
        if source_mode == "Upload XLSX":
            if upload is None:
                st.info("Upload an XLSX file or switch to Google Sheet URL.")
                st.stop()
            st.session_state.bundle = load_from_upload(upload.getvalue())
        else:
            st.session_state.bundle = load_from_url(url.strip())
    except Exception as exc:
        st.error(f"Could not load data: {exc}")
        st.stop()

bundle: AnalysisBundle = st.session_state.bundle
fit_0_120 = bundle.fits[CONDITION_015_0_120]
fit_after_120 = bundle.fits[CONDITION_015_AFTER_120]

prediction_temp_for_k = st.sidebar.number_input("k display temperature (C)", value=390.0, step=1.0)

metric_cols = st.columns(4)
metric_cols[0].metric("k1: 0-120 min", fit_label("", fit_0_120, prediction_temp_for_k).replace(": ", "", 1))
metric_cols[1].metric("k2: After 120 min", fit_label("", fit_after_120, prediction_temp_for_k).replace(": ", "", 1))
metric_cols[2].metric("Included intervals", int(bundle.intervals["fitting_included"].sum()))
metric_cols[3].metric("Rows loaded", len(bundle.intervals))

tabs = st.tabs(["Overview", "Arrhenius", "Prediction", "Constant Rate Schedule", "Data Review", "Log"])

with tabs[0]:
    st.subheader("Model overview")
    overview_rows = []
    for label, condition in [("k1: 0-120 min", CONDITION_015_0_120), ("k2: After 120 min", CONDITION_015_AFTER_120)]:
        fit = bundle.fits[condition]
        overview_rows.append(
            {
                "model": label,
                "status": fit.status,
                "slope": fit.slope,
                "intercept": fit.intercept,
                "Ea kJ/mol": fit.ea_kj_per_mol,
                "R squared": fit.r_squared,
                f"k@{prediction_temp_for_k:g}C min^-1": rate_from_fit(fit, prediction_temp_for_k) if fit.is_valid else None,
                "temperature range C": f"{fmt(fit.min_temperature_c)}-{fmt(fit.max_temperature_c)}",
                "interval count": fit.interval_count,
            }
        )
    st.dataframe(pd.DataFrame(overview_rows), use_container_width=True, hide_index=True)

with tabs[1]:
    st.subheader("Arrhenius fitting: ln(k) vs 1/T")
    st.write(fit_label("k1", fit_0_120, prediction_temp_for_k))
    st.write(fit_label("k2", fit_after_120, prediction_temp_for_k))
    if fit_0_120.is_valid or fit_after_120.is_valid:
        st.altair_chart(arrhenius_chart(bundle), use_container_width=True)
    summary_frames = []
    for label, condition in [("k1", CONDITION_015_0_120), ("k2", CONDITION_015_AFTER_120)]:
        summary = bundle.summaries[condition].copy()
        if not summary.empty:
            summary.insert(0, "model", label)
            summary_frames.append(summary)
    if summary_frames:
        st.dataframe(pd.concat(summary_frames, ignore_index=True), use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("Prediction")
    col1, col2, col3, col4 = st.columns(4)
    initial_mass = col1.number_input("Initial P mg", min_value=0.001, value=2000.0, step=100.0)
    temperature = col2.number_input("Temperature C", value=390.0, step=1.0)
    process_time = col3.number_input("Process time", min_value=0.001, value=4.0, step=0.5)
    time_unit = col4.selectbox("Time unit", ["hour", "min"])
    try:
        pred = predict_loss_composite(fit_0_120, fit_after_120, initial_mass, temperature, process_time, time_unit)
        pcols = st.columns(4)
        pcols[0].metric("Expected loss mg", f"{pred.predicted_loss_mg:.3g}")
        pcols[1].metric("Remaining P mg", f"{pred.remaining_mass_mg:.3g}")
        pcols[2].metric("Average rate mg/hour", f"{pred.q_mg_per_hour:.3g}")
        pcols[3].metric("Consumed %", f"{pred.consumed_fraction_percent:.3g}")
        st.write(" / ".join(f"{s.model}: {s.start_min:g}-{s.end_min:g} min, k={s.k_per_min:.6g} min^-1" for s in pred.segments))
        st.altair_chart(prediction_chart(pred), use_container_width=True)
    except Exception as exc:
        st.warning(str(exc))

with tabs[3]:
    st.subheader("Constant Rate Schedule")
    c1, c2, c3, c4 = st.columns(4)
    schedule_initial = c1.number_input("Initial P mg", min_value=0.001, value=2000.0, step=100.0)
    schedule_hours = c2.number_input("Process h", min_value=0.001, value=17.0, step=1.0)
    target_rate = c3.number_input("Target mg/h", min_value=0.001, value=110.0, step=5.0)
    minimum_rate = c4.number_input("Minimum mg/h", min_value=0.001, value=80.0, step=5.0)
    c5, c6, c7, c8 = st.columns(4)
    minimum_remaining = c5.number_input("Minimum remaining mg", min_value=0.0, value=50.0, step=10.0)
    start_temp = c6.number_input("Start C", value=330.0, step=1.0)
    end_temp = c7.number_input("End C", value=410.0, step=1.0)
    time_step = c8.number_input("Time step h", min_value=0.001, value=1.0, step=0.5)
    result = calculate_composite_schedule(
        fit_0_120,
        fit_after_120,
        initial_mass_mg=schedule_initial,
        minimum_remaining_mg=minimum_remaining,
        total_hours=schedule_hours,
        target_average_mg_hour=target_rate,
        minimum_instant_mg_hour=minimum_rate,
        start_temperature_c=start_temp,
        end_temperature_c=end_temp,
        time_step_hours=time_step,
    )
    st.text(result.message)
    if not result.stages.empty:
        st.dataframe(result.stages, use_container_width=True, hide_index=True)
        csv = result.stages.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Download schedule CSV", data=csv, file_name="constant_rate_schedule.csv", mime="text/csv")

with tabs[4]:
    st.subheader("Data Review")
    review_cols = [
        "fitting_included",
        "time_group",
        "condition",
        "t1_min",
        "t2_min",
        "parsed_temperature_C",
        "p1_mg",
        "p2_mg",
        "interval_loss_mg",
        "duration_min",
        "rate_mg_per_hour",
        "exclusion_reason",
        "source_sheet",
        "excel_row",
    ]
    visible_cols = [c for c in review_cols if c in bundle.intervals.columns]
    st.dataframe(bundle.intervals[visible_cols], use_container_width=True)

with tabs[5]:
    st.subheader("Log")
    st.code("\n".join(bundle.logs), language="text")
