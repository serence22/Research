from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from urllib.request import Request, urlopen

import pandas as pd

from .arrhenius_model import ArrheniusFit, fit_arrhenius, summarize_temperature_rates
from .constants import FIT_CONDITIONS
from .summary_sheet_loader import build_summary_intervals, read_summary_sheet


@dataclass
class AnalysisBundle:
    file_path: Path | str
    raw_formula: pd.DataFrame
    raw_full: pd.DataFrame
    formula_intervals: pd.DataFrame
    full_intervals: pd.DataFrame
    intervals: pd.DataFrame
    summaries: dict[str, pd.DataFrame]
    fits: dict[str, ArrheniusFit]
    logs: list[str]
    base_logs: list[str] | None = None


def _is_url(source: str | Path) -> bool:
    text = str(source).strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _google_sheet_export_url(url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        raise ValueError("Google Sheets URL에서 spreadsheet id를 찾을 수 없습니다.")
    sheet_id = match.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"


def _read_remote_workbook(url: str) -> BytesIO:
    export_url = _google_sheet_export_url(url) if "docs.google.com/spreadsheets" in url else url
    request = Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30) as response:
            data = response.read()
    except Exception as exc:
        raise ValueError(
            "Google Sheets를 읽지 못했습니다. 시트가 링크 접근 허용 상태인지 확인해주세요. "
            "비공개 시트는 Google 인증 연동이 필요합니다."
        ) from exc
    if not data:
        raise ValueError("Google Sheets export 결과가 비어 있습니다.")
    return BytesIO(data)


def _fit_selected_intervals(intervals: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, ArrheniusFit], list[str]]:
    intervals["fitting_included"] = intervals["fitting_included"].fillna(False).astype(bool)
    summaries: dict[str, pd.DataFrame] = {}
    fits: dict[str, ArrheniusFit] = {}
    logs: list[str] = []
    for condition in FIT_CONDITIONS:
        summary = summarize_temperature_rates(intervals, condition)
        summaries[condition] = summary
        fits[condition] = fit_arrhenius(summary, condition)
        fit = fits[condition]
        selected_count = int(
            ((intervals["condition"] == condition) & (intervals["fitting_included"] == True)).sum()
        )
        if fit.is_valid:
            logs.append(
                f"{condition}: selected intervals={selected_count}, A={fit.a_mg_per_min:.6g} min^-1, "
                f"ln(A)={fit.ln_a:.6g}, Ea={fit.ea_kj_per_mol:.6g} kJ/mol, "
                f"slope={fit.slope:.6g}, intercept={fit.intercept:.6g}, R^2={fit.r_squared:.4f}"
            )
        else:
            logs.append(f"{condition}: selected intervals={selected_count}, fitting failed - {fit.warning}")
    return summaries, fits, logs


def refit_bundle_from_selection(bundle: AnalysisBundle) -> None:
    summaries, fits, fit_logs = _fit_selected_intervals(bundle.intervals)
    bundle.summaries = summaries
    bundle.fits = fits
    base_logs = bundle.base_logs or bundle.logs
    selected_total = int(bundle.intervals["fitting_included"].fillna(False).astype(bool).sum())
    bundle.logs = base_logs + ["", f"Selected fitting intervals: {selected_total}"] + fit_logs


def run_analysis(file_path: str | Path) -> AnalysisBundle:
    source_text = str(file_path).strip()
    if _is_url(source_text):
        workbook_source = _read_remote_workbook(source_text)
        source_label: Path | str = source_text
        source_log = "Data source: Google Sheets URL export, 정리본 sheet only"
    else:
        path = Path(file_path)
        workbook_source = path
        source_label = path
        source_log = "Data source: local workbook, 정리본 sheet only"

    summary_rows = read_summary_sheet(workbook_source)
    intervals = build_summary_intervals(summary_rows)
    intervals["fitting_included"] = intervals["fitting_included"].fillna(False).astype(bool)

    logs = [
        source_log,
        f"정리본 rows loaded: {len(summary_rows)}",
        "No data from 수식, 전체 기록, or other sheets is used.",
    ]
    summaries, fits, fit_logs = _fit_selected_intervals(intervals)
    logs.extend(fit_logs)

    logs.append("0.15 Torr / Ar 20 sccm rows are split into 0-120 min and After 120 min conditions.")
    logs.append("0.02 Torr rows are excluded from condition menus and fitting.")
    logs.append("Arrhenius fitting uses x = 1/T and y = ln(k), where k = -ln(p2/p1)/(t2-t1) in min^-1.")
    base_logs = list(logs)

    return AnalysisBundle(
        file_path=source_label,
        raw_formula=summary_rows,
        raw_full=pd.DataFrame(),
        formula_intervals=intervals.copy(),
        full_intervals=pd.DataFrame(),
        intervals=intervals,
        summaries=summaries,
        fits=fits,
        logs=logs,
        base_logs=base_logs,
    )
