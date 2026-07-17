from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
from statistics import mean, median, stdev
from typing import Iterable, Sequence

import pandas as pd


SHEET_NAME = "수식"
HEADER_ROW_EXCEL = 90
DATA_FIRST_ROW_EXCEL = 91
DATA_LAST_ROW_EXCEL = 106
NROWS = DATA_LAST_ROW_EXCEL - DATA_FIRST_ROW_EXCEL + 1
USECOLS = "A:J"

TARGET_PRESSURE_TORR = 0.15
PRESSURE_TOLERANCE = 0.005
R_GAS = 8.314462618


COLUMN_ALIASES = {
    "cvd_type": ("CVD 종류", "CVD종류"),
    "pressure": ("공정 압력", "공정압력"),
    "temperature": ("온도", "실제 온도"),
    "t1": ("T1(min.)", "T1", "T1(min)"),
    "t2": ("T2(min.)", "T2", "T2(min)"),
    "p1": ("p1 (mg)", "p1(mg)", "p1"),
    "p2": ("p2(mg)", "p2 (mg)", "p2"),
    "duration_declared": ("T2-T1", "T2 - T1"),
}


@dataclass
class IntervalRecord:
    use: bool
    excel_row: int
    cvd_type: str
    pressure_raw: object
    pressure_torr: float | None
    temperature_raw: object
    temperature_c: float | None
    t1_min: float | None
    t2_min: float | None
    p1_mg: float | None
    p2_mg: float | None
    duration_min: float | None
    interval_loss_mg: float | None
    rate_mg_per_min: float | None
    rate_mg_per_hour: float | None
    included: bool
    exclusion_reason: str


@dataclass
class TemperatureSummary:
    temperature_c: float
    temperature_k: float
    interval_count: int
    total_duration_min: float
    total_loss_mg: float
    weighted_rate_mg_per_min: float
    arithmetic_rate_mg_per_min: float
    median_rate_mg_per_min: float
    std_rate_mg_per_min: float
    representative_rate_mg_per_min: float
    representative_method: str

    @property
    def representative_rate_mg_per_hour(self) -> float:
        return self.representative_rate_mg_per_min * 60


@dataclass
class FitResult:
    slope: float
    intercept: float
    r_squared: float
    rmse: float
    ea_j_per_mol: float
    ea_kj_per_mol: float
    a_mg_per_min: float
    temperature_count: int
    interval_count: int
    min_temperature_c: float
    max_temperature_c: float


@dataclass
class AnalysisResult:
    records: list[IntervalRecord]
    summaries: list[TemperatureSummary]
    fit: FitResult | None
    logs: list[str]
    method: str


def clean_column_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = {col: clean_column_name(col) for col in df.columns}
    df = df.rename(columns=cleaned)
    rename: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for col in df.columns:
            if clean_column_name(col) in aliases:
                rename[col] = canonical
                break
    missing = [name for name in ("cvd_type", "pressure", "temperature", "t1", "t2", "p1", "p2") if name not in rename.values()]
    if missing:
        label = ", ".join(missing)
        raise ValueError(f"필수 열을 찾을 수 없습니다: {label}")
    return df.rename(columns=rename)


def read_source_sheet(file_path: str | Path) -> pd.DataFrame:
    try:
        return pd.read_excel(
            file_path,
            sheet_name=SHEET_NAME,
            header=HEADER_ROW_EXCEL - 1,
            nrows=NROWS,
            usecols=USECOLS,
            engine="openpyxl",
        )
    except ValueError as exc:
        if SHEET_NAME in str(exc) or "Worksheet" in str(exc):
            raise ValueError('"수식" 시트를 찾을 수 없습니다. 다른 시트로 대체하지 않습니다.') from exc
        raise


def parse_number(value: object) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def parse_pressure_torr(value: object) -> float | None:
    return parse_number(value)


def is_target_pressure(value: float | None) -> bool:
    return value is not None and abs(value - TARGET_PRESSURE_TORR) <= PRESSURE_TOLERANCE


def parse_temperature_raw(value: object) -> tuple[float | None, bool]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None, False
    if isinstance(value, (int, float)):
        return float(value), True
    text = str(value).strip()
    if "=" in text:
        rhs = text.split("=", 1)[1]
        parsed = parse_number(rhs)
        return parsed, parsed is not None
    return None, False


def can_forward_fill_temperature(prev: dict[str, object] | None, current: dict[str, object]) -> bool:
    if not prev:
        return False
    if str(prev.get("cvd_type", "")).strip() != str(current.get("cvd_type", "")).strip():
        return False
    if parse_pressure_torr(prev.get("pressure")) != parse_pressure_torr(current.get("pressure")):
        return False
    prev_t2 = parse_number(prev.get("t2"))
    cur_t1 = parse_number(current.get("t1"))
    return prev_t2 is not None and cur_t1 is not None and abs(prev_t2 - cur_t1) < 1e-9


def build_records(df: pd.DataFrame) -> list[IntervalRecord]:
    df = normalize_columns(df)
    records: list[IntervalRecord] = []
    prev_context: dict[str, object] | None = None
    prev_actual_temp: float | None = None
    prev_had_explicit_actual_temp = False

    for idx, row in df.reset_index(drop=True).iterrows():
        excel_row = DATA_FIRST_ROW_EXCEL + idx
        context = row.to_dict()
        pressure = parse_pressure_torr(row.get("pressure"))
        temp, explicit_temp = parse_temperature_raw(row.get("temperature"))
        if temp is None and can_forward_fill_temperature(prev_context, context) and prev_had_explicit_actual_temp:
            temp = prev_actual_temp

        t1 = parse_number(row.get("t1"))
        t2 = parse_number(row.get("t2"))
        p1 = parse_number(row.get("p1"))
        p2 = parse_number(row.get("p2"))

        duration = t2 - t1 if t1 is not None and t2 is not None else None
        loss = p1 - p2 if p1 is not None and p2 is not None else None
        rate_min = loss / duration if loss is not None and duration not in (None, 0) else None
        rate_hour = rate_min * 60 if rate_min is not None else None

        reasons: list[str] = []
        if not is_target_pressure(pressure):
            reasons.append("Excluded: working pressure is not 0.15 Torr")
        if temp is None:
            reasons.append("온도 확인 필요")
        if t1 is None or t2 is None:
            reasons.append("T1/T2가 숫자가 아님")
        elif t2 <= t1:
            reasons.append("T2 <= T1")
        if p1 is None or p2 is None:
            reasons.append("p1 또는 p2가 숫자가 아님")
        elif p1 <= p2:
            reasons.append("p1 <= p2")
        if duration is not None and duration <= 0:
            reasons.append("duration_min <= 0")
        if rate_min is not None and rate_min <= 0:
            reasons.append("rate_mg_per_min <= 0")

        included = not reasons
        records.append(
            IntervalRecord(
                use=included,
                excel_row=excel_row,
                cvd_type=str(row.get("cvd_type", "")).strip(),
                pressure_raw=row.get("pressure"),
                pressure_torr=pressure,
                temperature_raw=row.get("temperature"),
                temperature_c=temp,
                t1_min=t1,
                t2_min=t2,
                p1_mg=p1,
                p2_mg=p2,
                duration_min=duration,
                interval_loss_mg=loss,
                rate_mg_per_min=rate_min,
                rate_mg_per_hour=rate_hour,
                included=included,
                exclusion_reason="; ".join(reasons),
            )
        )

        prev_context = context
        prev_actual_temp = temp
        prev_had_explicit_actual_temp = explicit_temp

    return records


def summarize_by_temperature(records: Iterable[IntervalRecord], method: str) -> list[TemperatureSummary]:
    groups: dict[float, list[IntervalRecord]] = {}
    for record in records:
        if record.included and record.temperature_c is not None:
            groups.setdefault(float(record.temperature_c), []).append(record)

    summaries: list[TemperatureSummary] = []
    for temp_c in sorted(groups):
        rows = groups[temp_c]
        durations = [r.duration_min for r in rows if r.duration_min is not None]
        losses = [r.interval_loss_mg for r in rows if r.interval_loss_mg is not None]
        rates = [r.rate_mg_per_min for r in rows if r.rate_mg_per_min is not None]
        total_duration = sum(durations)
        total_loss = sum(losses)
        weighted = total_loss / total_duration
        arithmetic = mean(rates)
        med = median(rates)
        sd = stdev(rates) if len(rates) > 1 else 0.0
        if method == "Arithmetic mean":
            representative = arithmetic
        elif method == "Median":
            representative = med
        else:
            representative = weighted
            method = "Duration-weighted mean"
        summaries.append(
            TemperatureSummary(
                temperature_c=temp_c,
                temperature_k=temp_c + 273.15,
                interval_count=len(rows),
                total_duration_min=total_duration,
                total_loss_mg=total_loss,
                weighted_rate_mg_per_min=weighted,
                arithmetic_rate_mg_per_min=arithmetic,
                median_rate_mg_per_min=med,
                std_rate_mg_per_min=sd,
                representative_rate_mg_per_min=representative,
                representative_method=method,
            )
        )
    return summaries


def linear_regression(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float]:
    x_bar = mean(xs)
    y_bar = mean(ys)
    ss_xx = sum((x - x_bar) ** 2 for x in xs)
    ss_yy = sum((y - y_bar) ** 2 for y in ys)
    ss_xy = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys))
    if ss_xx == 0 or ss_yy == 0:
        raise ValueError("회귀에 필요한 온도 또는 속도 변동이 부족합니다.")
    slope = ss_xy / ss_xx
    intercept = y_bar - slope * x_bar
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy)
    return slope, intercept, r_squared


def fit_arrhenius(summaries: Sequence[TemperatureSummary]) -> FitResult | None:
    usable = [s for s in summaries if s.representative_rate_mg_per_min > 0]
    if len(usable) < 3:
        return None
    xs = [1 / s.temperature_k for s in usable]
    ys = [math.log(s.representative_rate_mg_per_min) for s in usable]
    slope, intercept, r_squared = linear_regression(xs, ys)
    fitted = [slope * x + intercept for x in xs]
    rmse = math.sqrt(mean((y - y_hat) ** 2 for y, y_hat in zip(ys, fitted)))
    ea_j = -slope * R_GAS
    temps = [s.temperature_c for s in usable]
    return FitResult(
        slope=slope,
        intercept=intercept,
        r_squared=r_squared,
        rmse=rmse,
        ea_j_per_mol=ea_j,
        ea_kj_per_mol=ea_j / 1000,
        a_mg_per_min=math.exp(intercept),
        temperature_count=len(usable),
        interval_count=sum(s.interval_count for s in usable),
        min_temperature_c=min(temps),
        max_temperature_c=max(temps),
    )


def build_logs(records: Sequence[IntervalRecord], summaries: Sequence[TemperatureSummary]) -> list[str]:
    selected = [r for r in records if is_target_pressure(r.pressure_torr)]
    excluded_0029 = [r for r in records if r.pressure_torr is not None and abs(r.pressure_torr - 0.029) <= 0.005]
    temps = sorted({r.temperature_c for r in selected if r.temperature_c is not None})
    counts = ", ".join(f"{s.temperature_c:g}℃: {s.interval_count}" for s in summaries)
    return [
        "Data source sheet: 수식",
        "Header row: 90",
        "Data rows: 91-106",
        "Used columns: A:J",
        "Working pressure: 0.15 Torr",
        "Carrier gas: Ar 20 sccm",
        f"전체 읽은 행 수: {len(records)}",
        f"0.15 Torr로 선택된 행 수: {len(selected)}",
        f"0.029 Torr로 제외된 행 수: {len(excluded_0029)}",
        "파싱된 온도 목록: " + ", ".join(f"{t:g}℃" for t in temps),
        "온도별 유효 interval 개수: " + counts,
    ]


def analyze_file(file_path: str | Path, method: str = "Duration-weighted mean") -> AnalysisResult:
    df = read_source_sheet(file_path)
    if df.dropna(how="all").empty:
        raise ValueError("지정된 Excel 91-106행 범위에서 유효한 데이터가 없습니다.")
    records = build_records(df)
    summaries = summarize_by_temperature(records, method)
    fit = fit_arrhenius(summaries)
    logs = build_logs(records, summaries)
    if fit is None:
        logs.append("유효 온도가 3개 미만이므로 Arrhenius fitting을 중단했습니다.")
    return AnalysisResult(records=records, summaries=summaries, fit=fit, logs=logs, method=method)


def predict_rate_mg_per_min(fit: FitResult, temperature_c: float) -> float:
    temperature_k = temperature_c + 273.15
    return fit.a_mg_per_min * math.exp(-fit.ea_j_per_mol / (R_GAS * temperature_k))
