from __future__ import annotations

from typing import Any

import pandas as pd

from .constants import CONDITION_002, CONDITION_015
from .excel_loader import load_raw_sheets
from .parsing import (
    canonical_pressure,
    clean_column_name,
    infer_loading_class,
    normalize_equipment,
    parse_first_number,
    parse_pressure,
    parse_temperature,
    validate_or_infer_ar,
)


FORMULA_ALIASES = {
    "original_CVD_name": ("CVD 종류", "CVD종류"),
    "pressure": ("공정 압력", "공정압력"),
    "temperature": ("온도", "실제 온도"),
    "t1": ("T1(min.)", "T1(min)", "T1"),
    "t2": ("T2(min.)", "T2(min)", "T2"),
    "p1": ("p1 (mg)", "p1(mg)", "p1"),
    "p2": ("p2 (mg)", "p2(mg)", "p2"),
}

FULL_ALIASES = {
    "original_CVD_name": ("CVD 종류",),
    "base_pressure": ("Base Pressure", "공정 압력"),
    "working_pressure": ("Working Pressure(torr)", "Working Pressure", "Working Pressure (torr)"),
    "temperature": ("실제 온도", "온도"),
    "time": ("시간(min)", "시간"),
    "initial_p": ("초기 P (mg)", "초기 P"),
    "remaining_p": ("잔여 P (mg)", "잔류 P"),
    "excel_loss": ("P 소모량 (mg)", "P 소모량"),
    "ar_sccm": ("Ar (sccm)", "Ar"),
    "notes": ("비고",),
}


def _resolve_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    cleaned = {clean_column_name(c): c for c in df.columns}
    for alias in aliases:
        if alias in cleaned:
            return cleaned[alias]
    return None


def _value(row: pd.Series, col: str | None) -> Any:
    return row[col] if col and col in row else None


def _series_id(condition: str, equipment: str, loading: int | None, temp: float | None, source: str, block: int) -> str:
    temp_part = "manual" if temp is None else f"{temp:g}C"
    loading_part = "unknown" if loading is None else f"{loading}mg"
    condition_part = "015" if condition == CONDITION_015 else "002"
    return f"{condition_part}_{equipment}_{loading_part}_{temp_part}_{source}_series{block}"


def preprocess_formula_rows(formula: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    logs: list[str] = []
    cols = {name: _resolve_column(formula, aliases) for name, aliases in FORMULA_ALIASES.items()}
    missing = [name for name in ("original_CVD_name", "pressure", "temperature", "t1", "t2", "p1", "p2") if cols.get(name) is None]
    if missing:
        raise ValueError(f"수식 시트 필수 열 누락: {missing}")

    rows: list[dict[str, Any]] = []
    prev_key = None
    prev_t2 = None
    prev_temp_calibrated = False
    block = 0

    for _, raw in formula.iterrows():
        original_cvd = _value(raw, cols["original_CVD_name"])
        original_pressure = _value(raw, cols["pressure"])
        effective_pressure = parse_pressure(original_pressure)
        canonical, condition, pressure_note = canonical_pressure(effective_pressure)
        ar_sccm, inferred_ar, ar_error = validate_or_infer_ar(None, canonical)
        temp_raw = _value(raw, cols["temperature"])
        temp, temp_method, temp_override, temp_note = parse_temperature(temp_raw, prev_temp_calibrated)
        equipment = normalize_equipment(original_cvd)
        p1 = parse_first_number(_value(raw, cols["p1"]))
        p2 = parse_first_number(_value(raw, cols["p2"]))
        t1 = parse_first_number(_value(raw, cols["t1"]))
        t2 = parse_first_number(_value(raw, cols["t2"]))
        loading = infer_loading_class(original_cvd, p1)

        key = (condition, equipment, loading, temp)
        if key != prev_key or (prev_t2 is not None and t1 is not None and abs(t1 - prev_t2) > 1e-9):
            block += 1
        series = _series_id(condition or "excluded", equipment, loading, temp, "formula", block)

        reasons: list[str] = []
        if condition is None:
            reasons.append(pressure_note)
        if ar_error:
            reasons.append(ar_error)
        if temp is None:
            reasons.append("온도 파싱 실패")
        if t1 is None or t2 is None or p1 is None or p2 is None:
            reasons.append("T1/T2/p1/p2 누락")
        elif t2 <= t1:
            reasons.append("T2 <= T1")
        elif p1 <= p2:
            reasons.append("p1 <= p2")

        rows.append(
            {
                "use": not reasons,
                "source_sheet": "수식",
                "excel_row": int(raw["excel_row"]),
                "source_priority": 1,
                "original_CVD_name": original_cvd,
                "normalized_equipment": equipment,
                "loading_class": loading,
                "series_id": series,
                "original_pressure": original_pressure,
                "effective_pressure": effective_pressure,
                "canonical_pressure": canonical,
                "condition": condition,
                "pressure_note": pressure_note,
                "ar_sccm": ar_sccm,
                "inferred_ar": inferred_ar,
                "original_temperature": temp_raw,
                "parsed_temperature_C": temp,
                "temperature_parse_method": temp_method,
                "temperature_override_applied": temp_override,
                "temperature_correction_note": temp_note,
                "t1_min": t1,
                "t2_min": t2,
                "initial_p_mg": None,
                "remaining_p_mg": None,
                "p1_mg": p1,
                "p2_mg": p2,
                "cumulative_loss_mg": None,
                "interval_loss_mg": None,
                "duration_min": None,
                "rate_mg_per_min": None,
                "rate_mg_per_hour": None,
                "startup_interval": False,
                "merged_interval": False,
                "direct_interval": True,
                "source_rows": str(int(raw["excel_row"])),
                "duplicate_status": "",
                "fitting_included": False,
                "exclusion_reason": "; ".join(reasons),
                "notes": "",
            }
        )
        prev_key = key
        prev_t2 = t2
        prev_temp_calibrated = bool(temp_override and temp == 373.5)
    return pd.DataFrame(rows), logs


def preprocess_full_record_rows(full: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    logs: list[str] = []
    cols = {name: _resolve_column(full, aliases) for name, aliases in FULL_ALIASES.items()}
    missing = [name for name in ("original_CVD_name", "temperature", "time", "initial_p", "remaining_p") if cols.get(name) is None]
    if missing:
        raise ValueError(f"전체 기록 필수 열 누락: {missing}")

    rows: list[dict[str, Any]] = []
    block = 0
    last_key = None
    for _, raw in full.iterrows():
        original_cvd = _value(raw, cols["original_CVD_name"])
        working_pressure = _value(raw, cols["working_pressure"])
        base_pressure = _value(raw, cols["base_pressure"])
        original_pressure = working_pressure if parse_pressure(working_pressure) is not None else base_pressure
        effective_pressure = parse_pressure(original_pressure)
        canonical, condition, pressure_note = canonical_pressure(effective_pressure)
        ar_sccm, inferred_ar, ar_error = validate_or_infer_ar(_value(raw, cols["ar_sccm"]), canonical)
        temp_raw = _value(raw, cols["temperature"])
        temp, temp_method, temp_override, temp_note = parse_temperature(temp_raw)
        equipment = normalize_equipment(original_cvd)
        initial_p = parse_first_number(_value(raw, cols["initial_p"]))
        remaining_p = parse_first_number(_value(raw, cols["remaining_p"]))
        time_min = parse_first_number(_value(raw, cols["time"]))
        excel_loss = parse_first_number(_value(raw, cols["excel_loss"]))
        loading = infer_loading_class(original_cvd, initial_p)
        key = (condition, equipment, loading, temp)
        if key != last_key:
            block += 1
        series = _series_id(condition or "excluded", equipment, loading, temp, "full", block)

        cumulative_loss = None
        reasons: list[str] = []
        warnings: list[str] = []
        if condition is None:
            reasons.append(pressure_note)
        if ar_error:
            reasons.append(ar_error)
        if temp is None:
            reasons.append("온도 파싱 실패")
        if initial_p is None or remaining_p is None or time_min is None:
            reasons.append("초기/잔류량/시간 누락")
        elif time_min <= 0:
            reasons.append("공정시간 <= 0")
        else:
            cumulative_loss = initial_p - remaining_p
            if cumulative_loss <= 0:
                reasons.append("누적 소모량 <= 0")
            if excel_loss is not None and abs(cumulative_loss - excel_loss) > 1.0:
                warnings.append(f"Excel loss와 재계산 loss 차이 > 1 mg ({excel_loss:g} vs {cumulative_loss:g})")

        rows.append(
            {
                "use": not reasons,
                "source_sheet": "전체 기록",
                "excel_row": int(raw["excel_row"]),
                "source_priority": 2,
                "original_CVD_name": original_cvd,
                "normalized_equipment": equipment,
                "loading_class": loading,
                "series_id": series,
                "original_pressure": original_pressure,
                "effective_pressure": effective_pressure,
                "canonical_pressure": canonical,
                "condition": condition,
                "pressure_note": pressure_note,
                "ar_sccm": ar_sccm,
                "inferred_ar": inferred_ar,
                "original_temperature": temp_raw,
                "parsed_temperature_C": temp,
                "temperature_parse_method": temp_method,
                "temperature_override_applied": temp_override,
                "temperature_correction_note": temp_note,
                "time_min": time_min,
                "initial_p_mg": initial_p,
                "remaining_p_mg": remaining_p,
                "cumulative_loss_mg": cumulative_loss,
                "excel_loss_mg": excel_loss,
                "startup_interval": False,
                "merged_interval": False,
                "direct_interval": False,
                "source_rows": str(int(raw["excel_row"])),
                "duplicate_status": "",
                "fitting_included": False,
                "exclusion_reason": "; ".join(reasons),
                "notes": "; ".join(warnings),
            }
        )
        last_key = key
    return pd.DataFrame(rows), logs


def load_and_preprocess(file_path: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    formula_raw, full_raw, logs = load_raw_sheets(file_path)
    formula, formula_logs = preprocess_formula_rows(formula_raw)
    full, full_logs = preprocess_full_record_rows(full_raw)
    return formula, full, logs + formula_logs + full_logs
