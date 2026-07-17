from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .parsing import (
    canonical_pressure,
    infer_loading_class,
    normalize_equipment,
    parse_first_number,
    parse_pressure,
    parse_temperature,
    validate_or_infer_ar,
)
from .constants import BASE_CONDITION_015, CONDITION_015_0_120, CONDITION_015_AFTER_120


DATA_SHEET = "Codex"
FALLBACK_SHEET = "정리본"


def _rewind_if_possible(file_path: Any) -> None:
    if hasattr(file_path, "seek"):
        file_path.seek(0)


def _find_summary_sheet(file_path: str | Path | Any) -> str:
    _rewind_if_possible(file_path)
    xl = pd.ExcelFile(file_path, engine="openpyxl")
    fallback = None
    for sheet in xl.sheet_names:
        compact = sheet.replace(" ", "").lower()
        if compact == DATA_SHEET.lower():
            return sheet
        if compact == FALLBACK_SHEET:
            fallback = sheet
    if fallback is not None:
        return fallback
    raise ValueError('"Codex" 시트를 찾을 수 없습니다.')


def _clean_header(value: Any) -> str:
    return str(value).strip().replace("\n", " ")


def read_summary_sheet(file_path: str | Path | Any) -> pd.DataFrame:
    sheet = _find_summary_sheet(file_path)
    _rewind_if_possible(file_path)
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None, engine="openpyxl")
    if raw.empty:
        raise ValueError(f'"{sheet}" 시트가 비어 있습니다.')
    header_idx = None
    for idx, row in raw.iterrows():
        values = [_clean_header(v) for v in row.tolist()]
        compact = [value.replace(" ", "") for value in values]
        if "CVD종류" in compact:
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError(f'"{sheet}" 시트에서 header 행을 찾을 수 없습니다.')
    headers = [_clean_header(v) for v in raw.iloc[header_idx].tolist()]
    df = raw.iloc[header_idx + 1 :].copy()
    df.columns = headers
    df = df.dropna(how="all").reset_index(drop=True)
    df["excel_row"] = df.index + header_idx + 2
    df["source_sheet"] = sheet
    df["source_priority"] = 1
    return df


def _col(df: pd.DataFrame, *names: str) -> str:
    normalized = {str(c).replace(" ", "").lower(): c for c in df.columns}
    for name in names:
        key = name.replace(" ", "").lower()
        if key in normalized:
            return normalized[key]
    raise ValueError(f"Codex 필수 열을 찾을 수 없습니다: {names[0]}")


def _time_group(t1: float | None, t2: float | None) -> tuple[str | None, str | None]:
    if t1 is None or t2 is None:
        return None, "T1/T2 누락"
    if t2 <= t1:
        return None, "T2 <= T1"
    if 0 <= t1 and t2 <= 120:
        return "0-120 min", None
    if 120 <= t1:
        return "After 120 min", None
    if t1 < 120 < t2:
        return "120분 경계 교차", "120분 경계 교차"
    return None, "시간 구간 분류 불가"


def _condition_for_time_group(base_condition: str | None, t1: float | None, t2: float | None) -> tuple[str | None, str | None, str | None]:
    if base_condition != BASE_CONDITION_015:
        return None, None, "0.15 Torr / Ar 20 sccm 외 조건 제외"
    group, error = _time_group(t1, t2)
    if error:
        return None, group, error
    if group == "0-120 min":
        return CONDITION_015_0_120, group, None
    return CONDITION_015_AFTER_120, group, None


def build_summary_intervals(summary_df: pd.DataFrame) -> pd.DataFrame:
    cvd_col = _col(summary_df, "CVD 종류", "CVD종류")
    pressure_col = _col(summary_df, "공정 압력", "공정압력")
    temp_col = _col(summary_df, "온도", "실제 온도")
    t1_col = _col(summary_df, "T1(min.)", "T1(min)", "T1")
    t2_col = _col(summary_df, "T2(min.)", "T2(min)", "T2")
    p1_col = _col(summary_df, "p1 (mg)", "p1(mg)", "p1")
    p2_col = _col(summary_df, "p2(mg)", "p2 (mg)", "p2")

    rows: list[dict[str, Any]] = []
    for _, row in summary_df.iterrows():
        original_cvd = row[cvd_col]
        pressure_raw = row[pressure_col]
        pressure = parse_pressure(pressure_raw)
        canonical, base_condition, pressure_note = canonical_pressure(pressure)
        ar_sccm, inferred_ar, ar_error = validate_or_infer_ar(None, canonical)
        temp_raw = row[temp_col]
        temp_c, temp_method, temp_override, temp_note = parse_temperature(temp_raw)
        equipment = normalize_equipment(original_cvd)
        p1 = parse_first_number(row[p1_col])
        p2 = parse_first_number(row[p2_col])
        t1 = parse_first_number(row[t1_col])
        t2 = parse_first_number(row[t2_col])
        condition, time_group, time_group_error = _condition_for_time_group(base_condition, t1, t2)
        loading = infer_loading_class(original_cvd, p1)

        reasons: list[str] = []
        if base_condition is None:
            reasons.append(pressure_note)
        if ar_error:
            reasons.append(ar_error)
        if time_group_error:
            reasons.append(time_group_error)
        if temp_c is None:
            reasons.append("온도 파싱 실패")
        if t1 is None or t2 is None or p1 is None or p2 is None:
            reasons.append("T1/T2/p1/p2 누락")

        duration = None
        loss = None
        rate_min = None
        rate_hour = None
        k_first_order = None
        if not reasons:
            duration = t2 - t1
            loss = p1 - p2
            if duration <= 0:
                reasons.append("T2 <= T1")
            elif p1 <= 0 or p2 <= 0:
                reasons.append("p1/p2 <= 0")
            elif loss <= 0:
                reasons.append("p1 <= p2")
            else:
                rate_min = loss / duration
                rate_hour = rate_min * 60
                import math

                k_first_order = -math.log(p2 / p1) / duration

        source_row = int(row["excel_row"])
        series_id = (
            f"015_{time_group or 'unknown'}_{equipment}_{loading or 'unknown'}mg_{temp_c:g}C_summary_row{source_row}"
            if condition
            else f"excluded_summary_row{source_row}"
        )
        included = not reasons
        rows.append(
            {
                "use": included,
                "source_sheet": row.get("source_sheet", DATA_SHEET),
                "excel_row": source_row,
                "source_priority": 1,
                "original_CVD_name": original_cvd,
                "normalized_equipment": equipment,
                "loading_class": loading,
                "series_id": series_id,
                "original_pressure": pressure_raw,
                "effective_pressure": pressure,
                "canonical_pressure": canonical,
                "base_condition": base_condition,
                "time_group": time_group,
                "condition": condition,
                "pressure_note": pressure_note,
                "ar_sccm": ar_sccm,
                "inferred_ar": inferred_ar,
                "original_temperature": temp_raw,
                "parsed_temperature_C": temp_c,
                "temperature_parse_method": temp_method,
                "temperature_override_applied": temp_override,
                "temperature_correction_note": temp_note,
                "t1_min": t1,
                "t2_min": t2,
                "initial_p_mg": p1,
                "remaining_p_mg": p2,
                "p1_mg": p1,
                "p2_mg": p2,
                "cumulative_loss_mg": None,
                "interval_loss_mg": loss,
                "duration_min": duration,
                "rate_mg_per_min": rate_min,
                "rate_mg_per_hour": rate_hour,
                "k_first_order_per_min": k_first_order,
                "startup_interval": t1 == 0,
                "merged_interval": False,
                "direct_interval": True,
                "source_rows": str(source_row),
                "duplicate_status": "unique" if included else "",
                "fitting_included": included,
                "exclusion_reason": "; ".join(reasons),
                "notes": "Codex 탭 데이터 사용",
            }
        )
    return pd.DataFrame(rows)
